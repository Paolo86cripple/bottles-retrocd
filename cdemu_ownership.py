#!/usr/bin/env python3
"""Fail-closed ownership journal and inter-process lock for RetroCD CDEmu devices.

CDEmu's D-Bus API deliberately appends devices and RemoveDevice deliberately
removes only the final device.  RetroCD therefore needs durable evidence about
which appended suffix it created before it can safely clean that suffix after a
GUI crash.  This module contains no CDEmu mutation logic; it provides the
process lock and a strict, atomic journal consumed by the hardened GUI layer.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import stat
import tempfile
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


JOURNAL_SCHEMA = 1
APP_DIRNAME = "bottles-retro-cd"
_BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
_BOOT_RE = re.compile(r"^[0-9a-fA-F-]{16,64}$")
_SR_RE = re.compile(r"^/dev/sr[0-9]+$")
_SG_RE = re.compile(r"^/dev/sg[0-9]+$")


class CDEmuOwnershipError(RuntimeError):
    """Ownership evidence is missing, inconsistent, or unsafe to use."""


class CDEmuOwnershipBusy(CDEmuOwnershipError):
    """Another RetroCD process currently owns the CDEmu operation lock."""


@dataclass(frozen=True, slots=True)
class OwnedDevice:
    index: int
    image: str
    sr: str
    sg: str
    mount: str
    rdev: int

    def to_json(self) -> dict[str, object]:
        return {
            "index": self.index,
            "image": self.image,
            "sr": self.sr,
            "sg": self.sg,
            "mount": self.mount,
            "rdev": self.rdev,
        }

    @classmethod
    def from_json(cls, raw: object) -> "OwnedDevice":
        if not isinstance(raw, dict):
            raise CDEmuOwnershipError("Journal CDEmu: record device non è un oggetto JSON.")
        index = raw.get("index")
        image = raw.get("image")
        sr = raw.get("sr")
        sg = raw.get("sg")
        mount = raw.get("mount")
        rdev = raw.get("rdev")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise CDEmuOwnershipError("Journal CDEmu: indice device non valido.")
        if not isinstance(image, str) or not image.startswith("/") or "\x00" in image:
            raise CDEmuOwnershipError("Journal CDEmu: percorso immagine non valido.")
        if not isinstance(sr, str) or _SR_RE.fullmatch(sr) is None:
            raise CDEmuOwnershipError("Journal CDEmu: mapping /dev/srX non valido.")
        if not isinstance(sg, str) or (sg and _SG_RE.fullmatch(sg) is None):
            raise CDEmuOwnershipError("Journal CDEmu: mapping /dev/sgX non valido.")
        if not isinstance(mount, str) or not mount.startswith("/") or "\x00" in mount:
            raise CDEmuOwnershipError("Journal CDEmu: mount non valido.")
        if not isinstance(rdev, int) or isinstance(rdev, bool) or rdev <= 0:
            raise CDEmuOwnershipError("Journal CDEmu: identità rdev non valida.")
        return cls(index=index, image=image, sr=sr, sg=sg, mount=mount, rdev=rdev)


@dataclass(frozen=True, slots=True)
class PendingDevice:
    index: int
    image: str

    def to_json(self) -> dict[str, object]:
        return {"index": self.index, "image": self.image}

    @classmethod
    def from_json(cls, raw: object) -> "PendingDevice | None":
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise CDEmuOwnershipError("Journal CDEmu: record pending non valido.")
        index = raw.get("index")
        image = raw.get("image")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise CDEmuOwnershipError("Journal CDEmu: indice pending non valido.")
        if not isinstance(image, str) or not image.startswith("/") or "\x00" in image:
            raise CDEmuOwnershipError("Journal CDEmu: immagine pending non valida.")
        return cls(index=index, image=image)


@dataclass(frozen=True, slots=True)
class OwnershipSession:
    session_id: str
    phase: str
    boot_id: str
    daemon_identity: str
    owner_pid: int
    owner_start_ticks: int
    base_count: int
    expected_images: tuple[str, ...]
    resources: tuple[OwnedDevice, ...]
    pending: PendingDevice | None
    created_at: int

    def to_json(self) -> dict[str, object]:
        return {
            "schema": JOURNAL_SCHEMA,
            "session_id": self.session_id,
            "phase": self.phase,
            "boot_id": self.boot_id,
            "daemon_identity": self.daemon_identity,
            "owner_pid": self.owner_pid,
            "owner_start_ticks": self.owner_start_ticks,
            "base_count": self.base_count,
            "expected_images": list(self.expected_images),
            "resources": [item.to_json() for item in self.resources],
            "pending": self.pending.to_json() if self.pending is not None else None,
            "created_at": self.created_at,
        }

    @classmethod
    def from_json(cls, raw: object) -> "OwnershipSession":
        if not isinstance(raw, dict) or raw.get("schema") != JOURNAL_SCHEMA:
            raise CDEmuOwnershipError("Journal CDEmu: schema assente o incompatibile.")
        session_id = raw.get("session_id")
        phase = raw.get("phase")
        boot_id = raw.get("boot_id")
        daemon_identity = raw.get("daemon_identity")
        owner_pid = raw.get("owner_pid")
        owner_start_ticks = raw.get("owner_start_ticks")
        base_count = raw.get("base_count")
        expected_images = raw.get("expected_images")
        resources_raw = raw.get("resources")
        created_at = raw.get("created_at")

        if not isinstance(session_id, str) or _HEX32_RE.fullmatch(session_id) is None:
            raise CDEmuOwnershipError("Journal CDEmu: session_id non valido.")
        if phase not in {"preparing", "active", "cleanup"}:
            raise CDEmuOwnershipError("Journal CDEmu: fase non valida.")
        if not isinstance(boot_id, str) or _BOOT_RE.fullmatch(boot_id) is None:
            raise CDEmuOwnershipError("Journal CDEmu: boot_id non valido.")
        if not isinstance(daemon_identity, str) or not daemon_identity or len(daemon_identity) > 2048:
            raise CDEmuOwnershipError("Journal CDEmu: identità daemon non valida.")
        if not isinstance(owner_pid, int) or isinstance(owner_pid, bool) or owner_pid <= 0:
            raise CDEmuOwnershipError("Journal CDEmu: PID owner non valido.")
        if (
            not isinstance(owner_start_ticks, int)
            or isinstance(owner_start_ticks, bool)
            or owner_start_ticks <= 0
        ):
            raise CDEmuOwnershipError("Journal CDEmu: start-time owner non valido.")
        if not isinstance(base_count, int) or isinstance(base_count, bool) or base_count < 0:
            raise CDEmuOwnershipError("Journal CDEmu: base_count non valido.")
        if not isinstance(created_at, int) or isinstance(created_at, bool) or created_at <= 0:
            raise CDEmuOwnershipError("Journal CDEmu: timestamp non valido.")
        if not isinstance(expected_images, list) or not expected_images:
            raise CDEmuOwnershipError("Journal CDEmu: elenco immagini attese vuoto/non valido.")
        if not all(isinstance(item, str) and item.startswith("/") and "\x00" not in item for item in expected_images):
            raise CDEmuOwnershipError("Journal CDEmu: percorso immagine attesa non valido.")
        if len(set(expected_images)) != len(expected_images):
            raise CDEmuOwnershipError("Journal CDEmu: immagini attese duplicate.")
        if not isinstance(resources_raw, list):
            raise CDEmuOwnershipError("Journal CDEmu: elenco risorse non valido.")

        resources = tuple(OwnedDevice.from_json(item) for item in resources_raw)
        indices = [item.index for item in resources]
        if len(set(indices)) != len(indices):
            raise CDEmuOwnershipError("Journal CDEmu: indici device duplicati.")
        if len({item.sr for item in resources}) != len(resources):
            raise CDEmuOwnershipError("Journal CDEmu: mapping /dev/srX duplicati.")
        if len({item.image for item in resources}) != len(resources):
            raise CDEmuOwnershipError("Journal CDEmu: immagini risorsa duplicate.")
        if any(item.image not in expected_images for item in resources):
            raise CDEmuOwnershipError("Journal CDEmu: risorsa riferita a immagine non attesa.")

        pending = PendingDevice.from_json(raw.get("pending"))
        if pending is not None:
            if pending.image not in expected_images:
                raise CDEmuOwnershipError("Journal CDEmu: pending riferito a immagine non attesa.")
            if pending.index in set(indices):
                raise CDEmuOwnershipError("Journal CDEmu: indice pending già registrato come owned.")

        return cls(
            session_id=session_id,
            phase=phase,
            boot_id=boot_id,
            daemon_identity=daemon_identity,
            owner_pid=owner_pid,
            owner_start_ticks=owner_start_ticks,
            base_count=base_count,
            expected_images=tuple(expected_images),
            resources=resources,
            pending=pending,
            created_at=created_at,
        )


def state_home() -> Path:
    value = os.environ.get("XDG_STATE_HOME", "").strip()
    return Path(value) if value else Path.home() / ".local" / "state"


def host_boot_id() -> str:
    try:
        value = _BOOT_ID_PATH.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise CDEmuOwnershipError(f"Impossibile leggere boot_id host: {exc}") from exc
    if _BOOT_RE.fullmatch(value) is None:
        raise CDEmuOwnershipError("boot_id host non valido.")
    return value


def process_start_ticks(pid: int) -> int | None:
    """Return Linux /proc starttime (field 22), robust to spaces in comm."""
    try:
        text = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii")
    except OSError:
        return None
    end = text.rfind(")")
    if end < 0:
        return None
    fields = text[end + 2 :].split()
    # fields[0] is proc stat field 3 (state); field 22 is therefore index 19.
    if len(fields) <= 19:
        return None
    try:
        value = int(fields[19])
    except ValueError:
        return None
    return value if value > 0 else None


def session_owner_alive(session: OwnershipSession) -> bool:
    current = process_start_ticks(session.owner_pid)
    return current is not None and current == session.owner_start_ticks


def block_rdev(path: str) -> int:
    try:
        info = Path(path).stat()
    except OSError as exc:
        raise CDEmuOwnershipError(f"Device CDEmu non accessibile per rdev: {path}: {exc}") from exc
    if not stat.S_ISBLK(info.st_mode):
        raise CDEmuOwnershipError(f"Mapping CDEmu non è block device: {path}")
    if info.st_rdev <= 0:
        raise CDEmuOwnershipError(f"Mapping CDEmu privo di rdev valido: {path}")
    return int(info.st_rdev)


class CDEmuOwnershipStore:
    """Private journal plus a flock held for the lifetime of live ownership."""

    def __init__(self, root: Path | None = None):
        self.root = (root or (state_home() / APP_DIRNAME / "cdemu")).expanduser()
        self.journal_path = self.root / "ownership.json"
        self.lock_path = self.root / "operations.lock"
        self._session_fd: int | None = None
        self._thread_lock = threading.RLock()

    def _secure_root(self) -> Path:
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            os.chmod(self.root, 0o700)
            resolved = self.root.resolve(strict=True)
            info = resolved.stat()
        except OSError as exc:
            raise CDEmuOwnershipError(f"Directory stato CDEmu non preparabile: {self.root}: {exc}") from exc
        if not resolved.is_dir() or info.st_uid != os.getuid():
            raise CDEmuOwnershipError("Directory stato CDEmu non appartiene all'utente corrente.")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise CDEmuOwnershipError("Directory stato CDEmu non privata (richiesto 0700).")
        self.root = resolved
        self.journal_path = resolved / "ownership.json"
        self.lock_path = resolved / "operations.lock"
        return resolved

    def _open_lock(self) -> int:
        self._secure_root()
        flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.lock_path, flags, 0o600)
            os.fchmod(fd, 0o600)
            info = os.fstat(fd)
        except OSError as exc:
            raise CDEmuOwnershipError(f"Lock CDEmu non apribile: {exc}") from exc
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            os.close(fd)
            raise CDEmuOwnershipError("Lock CDEmu non è un file regolare privato dell'utente.")
        return fd

    @staticmethod
    def _flock(fd: int, timeout: float) -> None:
        deadline = time.monotonic() + max(0.0, timeout)
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise CDEmuOwnershipBusy(
                        "CDEmu è già gestito da un'altra sessione Bottles RetroCD; operazione rifiutata."
                    )
                time.sleep(0.05)

    def acquire_session_lock(self, timeout: float = 2.0) -> None:
        with self._thread_lock:
            if self._session_fd is not None:
                return
            fd = self._open_lock()
            try:
                self._flock(fd, timeout)
            except Exception:
                os.close(fd)
                raise
            self._session_fd = fd

    def release_session_lock(self) -> None:
        with self._thread_lock:
            fd = self._session_fd
            self._session_fd = None
            if fd is None:
                return
            with contextlib.suppress(OSError):
                fcntl.flock(fd, fcntl.LOCK_UN)
            with contextlib.suppress(OSError):
                os.close(fd)

    @contextmanager
    def operation(self, timeout: float = 2.0) -> Iterator[None]:
        """Serialize a short operation unless this store already holds the live lease."""
        with self._thread_lock:
            if self._session_fd is not None:
                yield
                return
            fd = self._open_lock()
            try:
                self._flock(fd, timeout)
                yield
            finally:
                with contextlib.suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
                with contextlib.suppress(OSError):
                    os.close(fd)

    def _require_session_lock(self) -> None:
        if self._session_fd is None:
            raise CDEmuOwnershipError("Operazione journal CDEmu senza lease di sessione.")

    def _fsync_root(self) -> None:
        try:
            fd = os.open(self.root, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0))
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _write(self, session: OwnershipSession) -> None:
        self._require_session_lock()
        root = self._secure_root()
        payload = json.dumps(session.to_json(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        fd, temp_name = tempfile.mkstemp(prefix=".ownership-", suffix=".tmp", dir=root)
        temp = Path(temp_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8", closefd=True) as fh:
                fd = -1
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp, self.journal_path)
            os.chmod(self.journal_path, 0o600)
            self._fsync_root()
        finally:
            if fd >= 0:
                with contextlib.suppress(OSError):
                    os.close(fd)
            with contextlib.suppress(FileNotFoundError):
                temp.unlink()

    def load(self) -> OwnershipSession | None:
        self._secure_root()
        try:
            info = self.journal_path.lstat()
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise CDEmuOwnershipError(f"Journal CDEmu non leggibile: {exc}") from exc
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise CDEmuOwnershipError("Journal CDEmu non è un file regolare dell'utente corrente.")
        if stat.S_IMODE(info.st_mode) & 0o077:
            raise CDEmuOwnershipError("Journal CDEmu non privato (richiesto 0600).")
        try:
            raw = json.loads(self.journal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CDEmuOwnershipError(f"Journal CDEmu corrotto/non leggibile: {exc}") from exc
        return OwnershipSession.from_json(raw)

    def begin(self, *, daemon_identity: str, base_count: int, expected_images: tuple[str, ...]) -> OwnershipSession:
        self._require_session_lock()
        if self.load() is not None:
            raise CDEmuOwnershipError(
                "Esiste già un journal CDEmu non risolto; nuova cache live rifiutata fino al recovery."
            )
        if not isinstance(base_count, int) or base_count < 0:
            raise CDEmuOwnershipError("base_count CDEmu non valido.")
        canonical = tuple(str(Path(item).resolve(strict=True)) for item in expected_images)
        if not canonical or len(set(canonical)) != len(canonical):
            raise CDEmuOwnershipError("Set immagini CDEmu vuoto o duplicato.")
        start = process_start_ticks(os.getpid())
        if start is None:
            raise CDEmuOwnershipError("Impossibile determinare start-time del processo RetroCD.")
        session = OwnershipSession(
            session_id=uuid.uuid4().hex,
            phase="preparing",
            boot_id=host_boot_id(),
            daemon_identity=str(daemon_identity),
            owner_pid=os.getpid(),
            owner_start_ticks=start,
            base_count=base_count,
            expected_images=canonical,
            resources=(),
            pending=None,
            created_at=int(time.time()),
        )
        self._write(session)
        return session

    def set_pending(self, *, index: int, image: str) -> OwnershipSession:
        self._require_session_lock()
        session = self.load()
        if session is None:
            raise CDEmuOwnershipError("Journal CDEmu mancante durante preparazione.")
        if session.pending is not None:
            raise CDEmuOwnershipError("Journal CDEmu contiene già un AddDevice pending.")
        canonical = str(Path(image).resolve(strict=True))
        expected_index = session.base_count + len(session.resources)
        if index != expected_index or canonical not in session.expected_images:
            raise CDEmuOwnershipError("Intent AddDevice non coerente con il suffisso CDEmu atteso.")
        updated = OwnershipSession(
            **{**session.__dict__, "pending": PendingDevice(index=index, image=canonical)}
        )
        self._write(updated)
        return updated

    def commit_pending(self, resource: OwnedDevice) -> OwnershipSession:
        self._require_session_lock()
        session = self.load()
        if session is None or session.pending is None:
            raise CDEmuOwnershipError("Nessun AddDevice pending da confermare nel journal CDEmu.")
        if resource.index != session.pending.index or resource.image != session.pending.image:
            raise CDEmuOwnershipError("Risorsa CDEmu non corrisponde all'intent pending.")
        resources = (*session.resources, resource)
        if [item.index for item in resources] != list(range(session.base_count, session.base_count + len(resources))):
            raise CDEmuOwnershipError("Risorse CDEmu non formano il suffisso contiguo atteso.")
        updated = OwnershipSession(
            session_id=session.session_id,
            phase=session.phase,
            boot_id=session.boot_id,
            daemon_identity=session.daemon_identity,
            owner_pid=session.owner_pid,
            owner_start_ticks=session.owner_start_ticks,
            base_count=session.base_count,
            expected_images=session.expected_images,
            resources=resources,
            pending=None,
            created_at=session.created_at,
        )
        self._write(updated)
        return updated

    def activate(self) -> OwnershipSession:
        self._require_session_lock()
        session = self.load()
        if session is None:
            raise CDEmuOwnershipError("Journal CDEmu mancante all'attivazione.")
        if session.pending is not None or len(session.resources) != len(session.expected_images):
            raise CDEmuOwnershipError("Cache CDEmu incompleta: journal non attivabile.")
        updated = OwnershipSession(
            session_id=session.session_id,
            phase="active",
            boot_id=session.boot_id,
            daemon_identity=session.daemon_identity,
            owner_pid=session.owner_pid,
            owner_start_ticks=session.owner_start_ticks,
            base_count=session.base_count,
            expected_images=session.expected_images,
            resources=session.resources,
            pending=None,
            created_at=session.created_at,
        )
        self._write(updated)
        return updated

    def mark_cleanup(self) -> OwnershipSession:
        self._require_session_lock()
        session = self.load()
        if session is None:
            raise CDEmuOwnershipError("Journal CDEmu mancante al cleanup.")
        updated = OwnershipSession(
            session_id=session.session_id,
            phase="cleanup",
            boot_id=session.boot_id,
            daemon_identity=session.daemon_identity,
            owner_pid=session.owner_pid,
            owner_start_ticks=session.owner_start_ticks,
            base_count=session.base_count,
            expected_images=session.expected_images,
            resources=session.resources,
            pending=session.pending,
            created_at=session.created_at,
        )
        self._write(updated)
        return updated

    def drop_last_resource(self, index: int) -> OwnershipSession:
        self._require_session_lock()
        session = self.load()
        if session is None or not session.resources:
            raise CDEmuOwnershipError("Journal CDEmu senza risorse da rimuovere.")
        if session.resources[-1].index != index:
            raise CDEmuOwnershipError("Cleanup journal non segue ordine LIFO CDEmu.")
        updated = OwnershipSession(
            session_id=session.session_id,
            phase="cleanup",
            boot_id=session.boot_id,
            daemon_identity=session.daemon_identity,
            owner_pid=session.owner_pid,
            owner_start_ticks=session.owner_start_ticks,
            base_count=session.base_count,
            expected_images=session.expected_images,
            resources=session.resources[:-1],
            pending=session.pending,
            created_at=session.created_at,
        )
        self._write(updated)
        return updated

    def clear(self) -> None:
        self._require_session_lock()
        with contextlib.suppress(FileNotFoundError):
            self.journal_path.unlink()
            self._fsync_root()

    def close(self) -> None:
        self.release_session_lock()


__all__ = [
    "CDEmuOwnershipBusy",
    "CDEmuOwnershipError",
    "CDEmuOwnershipStore",
    "OwnedDevice",
    "OwnershipSession",
    "PendingDevice",
    "block_rdev",
    "host_boot_id",
    "process_start_ticks",
    "session_owner_alive",
]
