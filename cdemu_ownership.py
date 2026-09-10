#!/usr/bin/env python3
"""Durable ownership evidence and fail-closed recovery for RetroCD CDEmu devices.

CDEmu appends devices and its RemoveDevice API removes only the final device.
RetroCD therefore records an exact appended suffix and holds an inter-process
flock while a live multidisc cache exists. Recovery never guesses ownership:
all destructive steps require the same host boot, same CDEmu daemon instance,
exact device count/index/mapping/rdev/media state and compatible RO mount state.
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
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterator, Protocol

JOURNAL_SCHEMA = 1
APP_DIRNAME = "bottles-retro-cd"
_BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
_HEX32_RE = re.compile(r"^[0-9a-f]{32}$")
_BOOT_RE = re.compile(r"^[0-9a-fA-F-]{16,64}$")
_SR_RE = re.compile(r"^/dev/sr[0-9]+$")
_SG_RE = re.compile(r"^/dev/sg[0-9]+$")


class CDEmuOwnershipError(RuntimeError):
    """Ownership evidence is absent, inconsistent or unsafe to use."""


class CDEmuOwnershipBusy(CDEmuOwnershipError):
    """Another RetroCD process currently owns the operation lock."""


class CDEmuLike(Protocol):
    def daemon_identity(self) -> str: ...
    def number_of_devices(self) -> int: ...
    def mapping(self, index: int) -> tuple[str, str]: ...
    def status(self, index: int) -> tuple[bool, tuple[str, ...]]: ...
    def unload(self, index: int) -> None: ...
    def wait_loaded(self, index: int, expected: bool, timeout: float = 8.0) -> tuple[bool, tuple[str, ...]]: ...
    def remove_last_device(self) -> None: ...


@dataclass(frozen=True, slots=True)
class OwnedDevice:
    index: int
    image: str
    sr: str
    sg: str
    mount: str
    rdev: int

    def to_json(self) -> dict[str, object]:
        return {"index": self.index, "image": self.image, "sr": self.sr, "sg": self.sg, "mount": self.mount, "rdev": self.rdev}

    @classmethod
    def from_json(cls, raw: object) -> "OwnedDevice":
        if not isinstance(raw, dict):
            raise CDEmuOwnershipError("Journal CDEmu: record device non valido.")
        index, image = raw.get("index"), raw.get("image")
        sr, sg, mount, rdev = raw.get("sr"), raw.get("sg"), raw.get("mount"), raw.get("rdev")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise CDEmuOwnershipError("Journal CDEmu: indice device non valido.")
        if not _absolute_string(image):
            raise CDEmuOwnershipError("Journal CDEmu: percorso immagine non valido.")
        if not isinstance(sr, str) or _SR_RE.fullmatch(sr) is None:
            raise CDEmuOwnershipError("Journal CDEmu: mapping /dev/srX non valido.")
        if not isinstance(sg, str) or (sg and _SG_RE.fullmatch(sg) is None):
            raise CDEmuOwnershipError("Journal CDEmu: mapping /dev/sgX non valido.")
        if not _absolute_string(mount):
            raise CDEmuOwnershipError("Journal CDEmu: mount non valido.")
        if not isinstance(rdev, int) or isinstance(rdev, bool) or rdev <= 0:
            raise CDEmuOwnershipError("Journal CDEmu: rdev non valido.")
        return cls(index, image, sr, sg, mount, rdev)


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
            raise CDEmuOwnershipError("Journal CDEmu: pending non valido.")
        index, image = raw.get("index"), raw.get("image")
        if not isinstance(index, int) or isinstance(index, bool) or index < 0:
            raise CDEmuOwnershipError("Journal CDEmu: indice pending non valido.")
        if not _absolute_string(image):
            raise CDEmuOwnershipError("Journal CDEmu: immagine pending non valida.")
        return cls(index, image)


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
    removing_index: int | None
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
            "pending": self.pending.to_json() if self.pending else None,
            "removing_index": self.removing_index,
            "created_at": self.created_at,
        }

    @classmethod
    def from_json(cls, raw: object) -> "OwnershipSession":
        if not isinstance(raw, dict) or raw.get("schema") != JOURNAL_SCHEMA:
            raise CDEmuOwnershipError("Journal CDEmu: schema assente o incompatibile.")
        session_id, phase = raw.get("session_id"), raw.get("phase")
        boot_id, daemon_identity = raw.get("boot_id"), raw.get("daemon_identity")
        owner_pid, owner_ticks = raw.get("owner_pid"), raw.get("owner_start_ticks")
        base_count, created_at = raw.get("base_count"), raw.get("created_at")
        expected_raw, resources_raw = raw.get("expected_images"), raw.get("resources")
        removing_index = raw.get("removing_index")
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
        if not isinstance(owner_ticks, int) or isinstance(owner_ticks, bool) or owner_ticks <= 0:
            raise CDEmuOwnershipError("Journal CDEmu: start-time owner non valido.")
        if not isinstance(base_count, int) or isinstance(base_count, bool) or base_count < 0:
            raise CDEmuOwnershipError("Journal CDEmu: base_count non valido.")
        if not isinstance(created_at, int) or isinstance(created_at, bool) or created_at <= 0:
            raise CDEmuOwnershipError("Journal CDEmu: timestamp non valido.")
        if not isinstance(expected_raw, list) or not expected_raw or not all(_absolute_string(x) for x in expected_raw):
            raise CDEmuOwnershipError("Journal CDEmu: immagini attese non valide.")
        if len(set(expected_raw)) != len(expected_raw):
            raise CDEmuOwnershipError("Journal CDEmu: immagini attese duplicate.")
        if not isinstance(resources_raw, list):
            raise CDEmuOwnershipError("Journal CDEmu: risorse non valide.")
        resources = tuple(OwnedDevice.from_json(item) for item in resources_raw)
        if [item.index for item in resources] != list(range(base_count, base_count + len(resources))):
            raise CDEmuOwnershipError("Journal CDEmu: risorse non formano il suffisso contiguo atteso.")
        if len({item.sr for item in resources}) != len(resources):
            raise CDEmuOwnershipError("Journal CDEmu: mapping sr duplicati.")
        if len({item.image for item in resources}) != len(resources):
            raise CDEmuOwnershipError("Journal CDEmu: immagini risorsa duplicate.")
        if any(item.image not in expected_raw for item in resources):
            raise CDEmuOwnershipError("Journal CDEmu: risorsa fuori dalle immagini attese.")
        pending = PendingDevice.from_json(raw.get("pending"))
        if pending is not None:
            if pending.image not in expected_raw or pending.index != base_count + len(resources):
                raise CDEmuOwnershipError("Journal CDEmu: pending non coerente col prossimo suffisso atteso.")
        if removing_index is not None:
            if not isinstance(removing_index, int) or isinstance(removing_index, bool):
                raise CDEmuOwnershipError("Journal CDEmu: removing_index non valido.")
            if not resources or removing_index != resources[-1].index or pending is not None:
                raise CDEmuOwnershipError("Journal CDEmu: removing_index incoerente.")
        return cls(session_id, phase, boot_id, daemon_identity, owner_pid, owner_ticks, base_count,
                   tuple(expected_raw), resources, pending, removing_index, created_at)


@dataclass(frozen=True, slots=True)
class CleanupResult:
    completed: bool
    obsolete_journal_cleared: bool
    messages: tuple[str, ...]


def _absolute_string(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value.startswith("/") and "\x00" not in value


def _canonical_text(value: str) -> str:
    return str(Path(os.path.abspath(os.path.expanduser(value))).resolve(strict=False))


def state_home() -> Path:
    raw = os.environ.get("XDG_STATE_HOME", "").strip()
    path = Path(raw).expanduser() if raw else Path.home() / ".local" / "state"
    if not path.is_absolute():
        raise CDEmuOwnershipError("XDG_STATE_HOME deve essere un percorso assoluto.")
    return path


def host_boot_id() -> str:
    try:
        value = _BOOT_ID_PATH.read_text(encoding="ascii").strip()
    except OSError as exc:
        raise CDEmuOwnershipError(f"Impossibile leggere boot_id host: {exc}") from exc
    if _BOOT_RE.fullmatch(value) is None:
        raise CDEmuOwnershipError("boot_id host non valido.")
    return value


def process_start_ticks(pid: int) -> int | None:
    try:
        text = (Path("/proc") / str(pid) / "stat").read_text(encoding="ascii")
    except OSError:
        return None
    end = text.rfind(")")
    fields = text[end + 2:].split() if end >= 0 else []
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
    if not stat.S_ISBLK(info.st_mode) or info.st_rdev <= 0:
        raise CDEmuOwnershipError(f"Mapping CDEmu non è un block device valido: {path}")
    return int(info.st_rdev)


class CDEmuOwnershipStore:
    """Private atomic journal plus a flock held for live ownership lifetime."""

    def __init__(self, root: Path | None = None):
        candidate = (root or (state_home() / APP_DIRNAME / "cdemu")).expanduser()
        if not candidate.is_absolute():
            raise CDEmuOwnershipError("Directory stato CDEmu deve essere assoluta.")
        self.root = candidate
        self.journal_path = candidate / "ownership.json"
        self.lock_path = candidate / "operations.lock"
        self._session_fd: int | None = None
        self._thread_lock = threading.RLock()

    @property
    def session_locked(self) -> bool:
        return self._session_fd is not None

    def _secure_root(self) -> Path:
        try:
            self.root.parent.mkdir(parents=True, exist_ok=True)
            if self.root.exists() or self.root.is_symlink():
                if stat.S_ISLNK(self.root.lstat().st_mode):
                    raise CDEmuOwnershipError("Directory stato CDEmu non può essere un symlink.")
            else:
                self.root.mkdir(mode=0o700)
            os.chmod(self.root, 0o700)
            resolved = self.root.resolve(strict=True)
            info = resolved.stat()
        except CDEmuOwnershipError:
            raise
        except OSError as exc:
            raise CDEmuOwnershipError(f"Directory stato CDEmu non preparabile: {self.root}: {exc}") from exc
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise CDEmuOwnershipError("Directory stato CDEmu deve essere directory privata 0700 dell'utente.")
        self.root = resolved
        self.journal_path, self.lock_path = resolved / "ownership.json", resolved / "operations.lock"
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
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            os.close(fd)
            raise CDEmuOwnershipError("Lock CDEmu deve essere file regolare privato 0600 dell'utente.")
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
                    raise CDEmuOwnershipBusy("CDEmu è già gestito da un'altra sessione Bottles RetroCD; operazione rifiutata.")
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
            fd, self._session_fd = self._session_fd, None
            if fd is not None:
                with contextlib.suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
                with contextlib.suppress(OSError):
                    os.close(fd)

    @contextmanager
    def operation(self, timeout: float = 2.0) -> Iterator[None]:
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

    def _require_lock(self) -> None:
        if self._session_fd is None:
            raise CDEmuOwnershipError("Scrittura journal CDEmu senza lease di sessione.")

    def _fsync_root(self) -> None:
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(self.root, flags)
        except OSError:
            return
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _write(self, session: OwnershipSession) -> None:
        self._require_lock()
        root = self._secure_root()
        payload = json.dumps(session.to_json(), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        fd, name = tempfile.mkstemp(prefix=".ownership-", suffix=".tmp", dir=root)
        temp = Path(name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
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
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
            raise CDEmuOwnershipError("Journal CDEmu deve essere file regolare privato 0600 dell'utente.")
        try:
            raw = json.loads(self.journal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CDEmuOwnershipError(f"Journal CDEmu corrotto/non leggibile: {exc}") from exc
        return OwnershipSession.from_json(raw)

    def begin(self, *, daemon_identity: str, base_count: int, expected_images: tuple[str, ...]) -> OwnershipSession:
        self._require_lock()
        if self.load() is not None:
            raise CDEmuOwnershipError("Esiste già un journal CDEmu non risolto; nuova cache live rifiutata.")
        canonical = tuple(_canonical_text(item) for item in expected_images)
        if not canonical or len(set(canonical)) != len(canonical):
            raise CDEmuOwnershipError("Set immagini CDEmu vuoto o duplicato.")
        if not isinstance(base_count, int) or base_count < 0:
            raise CDEmuOwnershipError("base_count CDEmu non valido.")
        ticks = process_start_ticks(os.getpid())
        if ticks is None:
            raise CDEmuOwnershipError("Impossibile determinare start-time del processo RetroCD.")
        session = OwnershipSession(uuid.uuid4().hex, "preparing", host_boot_id(), daemon_identity,
                                   os.getpid(), ticks, base_count, canonical, (), None, None, int(time.time()))
        self._write(session)
        return session

    def set_pending(self, *, index: int, image: str) -> OwnershipSession:
        self._require_lock()
        session = self.load()
        if session is None or session.pending is not None or session.removing_index is not None:
            raise CDEmuOwnershipError("Journal CDEmu non pronto per un nuovo AddDevice pending.")
        canonical = _canonical_text(image)
        if index != session.base_count + len(session.resources) or canonical not in session.expected_images:
            raise CDEmuOwnershipError("Intent AddDevice non coerente col suffisso/immagini attese.")
        updated = replace(session, pending=PendingDevice(index, canonical))
        self._write(updated)
        return updated

    def clear_pending_if_no_device(self, current_count: int) -> OwnershipSession:
        self._require_lock()
        session = self.load()
        if session is None or session.pending is None:
            raise CDEmuOwnershipError("Nessun pending da riconciliare.")
        expected_without_pending = session.base_count + len(session.resources)
        if current_count != expected_without_pending:
            raise CDEmuOwnershipError("Pending CDEmu ambiguo: un device potrebbe essere stato creato; cleanup automatico rifiutato.")
        updated = replace(session, pending=None)
        self._write(updated)
        return updated

    def commit_pending(self, resource: OwnedDevice) -> OwnershipSession:
        self._require_lock()
        session = self.load()
        if session is None or session.pending is None or session.removing_index is not None:
            raise CDEmuOwnershipError("Nessun AddDevice pending confermabile.")
        if resource.index != session.pending.index or resource.image != session.pending.image:
            raise CDEmuOwnershipError("Risorsa CDEmu diversa dall'intent pending.")
        resources = (*session.resources, resource)
        if [item.index for item in resources] != list(range(session.base_count, session.base_count + len(resources))):
            raise CDEmuOwnershipError("Risorse CDEmu non contigue.")
        updated = replace(session, resources=resources, pending=None)
        self._write(updated)
        return updated

    def activate(self) -> OwnershipSession:
        self._require_lock()
        session = self.load()
        if session is None or session.pending is not None or session.removing_index is not None:
            raise CDEmuOwnershipError("Journal CDEmu non attivabile nello stato corrente.")
        if len(session.resources) != len(session.expected_images):
            raise CDEmuOwnershipError("Cache CDEmu incompleta: journal non attivabile.")
        updated = replace(session, phase="active")
        self._write(updated)
        return updated

    def mark_cleanup(self) -> OwnershipSession:
        self._require_lock()
        session = self.load()
        if session is None or session.pending is not None:
            raise CDEmuOwnershipError("Journal CDEmu non pronto per cleanup distruttivo.")
        updated = replace(session, phase="cleanup")
        self._write(updated)
        return updated

    def set_removing(self, index: int) -> OwnershipSession:
        self._require_lock()
        session = self.load()
        if session is None or session.pending is not None or not session.resources:
            raise CDEmuOwnershipError("Journal CDEmu senza ultima risorsa rimovibile.")
        if session.resources[-1].index != index or session.removing_index not in {None, index}:
            raise CDEmuOwnershipError("Rimozione journal non LIFO o già ambigua.")
        updated = replace(session, phase="cleanup", removing_index=index)
        self._write(updated)
        return updated

    def commit_removed(self, index: int) -> OwnershipSession:
        self._require_lock()
        session = self.load()
        if session is None or not session.resources or session.removing_index != index:
            raise CDEmuOwnershipError("Commit rimozione CDEmu senza intent coerente.")
        if session.resources[-1].index != index:
            raise CDEmuOwnershipError("Commit rimozione CDEmu non LIFO.")
        updated = replace(session, resources=session.resources[:-1], removing_index=None, phase="cleanup")
        self._write(updated)
        return updated

    def clear(self) -> None:
        self._require_lock()
        with contextlib.suppress(FileNotFoundError):
            self.journal_path.unlink()
            self._fsync_root()

    def close(self) -> None:
        self.release_session_lock()


def _loaded_matches(resource: OwnedDevice, loaded: bool, filenames: tuple[str, ...]) -> bool:
    if not loaded:
        return not filenames
    return len(filenames) == 1 and _canonical_text(filenames[0]) == resource.image


def _validate_resource(resource: OwnedDevice, cdemu: CDEmuLike,
                       mount_info: Callable[[str], tuple[str | None, bool]],
                       validate_optical: Callable[[str], str]) -> tuple[bool, tuple[str, ...], str | None, bool]:
    mapped_sr, mapped_sg = cdemu.mapping(resource.index)
    if mapped_sr != resource.sr:
        raise CDEmuOwnershipError(f"Device #{resource.index}: mapping sr cambiato {resource.sr} → {mapped_sr}.")
    if resource.sg and mapped_sg != resource.sg:
        raise CDEmuOwnershipError(f"Device #{resource.index}: mapping sg cambiato {resource.sg} → {mapped_sg}.")
    if block_rdev(resource.sr) != resource.rdev:
        raise CDEmuOwnershipError(f"Device #{resource.index}: rdev di {resource.sr} cambiato.")
    validate_optical(resource.sr)
    loaded, filenames = cdemu.status(resource.index)
    if not _loaded_matches(resource, loaded, filenames):
        raise CDEmuOwnershipError(f"Device #{resource.index}: media/stato non corrisponde al journal ({filenames!r}).")
    target, ro = mount_info(resource.sr)
    if target and (target != resource.mount or not ro):
        raise CDEmuOwnershipError(f"Device #{resource.index}: mount inatteso/non-RO: {target!r}, ro={ro}.")
    return loaded, filenames, target, ro


def _validate_suffix(session: OwnershipSession, cdemu: CDEmuLike,
                     mount_info: Callable[[str], tuple[str | None, bool]],
                     validate_optical: Callable[[str], str]) -> None:
    expected = session.base_count + len(session.resources)
    current = cdemu.number_of_devices()
    if current != expected:
        raise CDEmuOwnershipError(f"Device count CDEmu ambiguo: {current}, atteso {expected}.")
    for resource in session.resources:
        _validate_resource(resource, cdemu, mount_info, validate_optical)


def cleanup_owned_session(store: CDEmuOwnershipStore, cdemu: CDEmuLike, *,
                          mount_info: Callable[[str], tuple[str | None, bool]],
                          unmount: Callable[[str], object],
                          validate_optical: Callable[[str], str],
                          stale_recovery: bool, sandbox_running: bool) -> CleanupResult:
    """Remove only a fully proven RetroCD-owned suffix; caller holds session lock."""
    if not store.session_locked:
        raise CDEmuOwnershipError("Cleanup CDEmu senza lock di sessione.")
    if sandbox_running:
        raise CDEmuOwnershipError("Cleanup CDEmu rifiutato mentre Bottles/Bubblejail è attivo.")
    session = store.load()
    if session is None:
        return CleanupResult(True, False, ("nessun journal CDEmu da ripulire",))
    if session.boot_id != host_boot_id() or session.daemon_identity != cdemu.daemon_identity():
        store.clear()
        return CleanupResult(True, True, ("journal CDEmu obsoleto: boot/daemon cambiato; nessun device corrente è stato toccato",))
    if stale_recovery and session_owner_alive(session):
        raise CDEmuOwnershipBusy("Il processo proprietario registrato nel journal CDEmu è ancora attivo.")

    if session.pending is not None:
        expected_without_pending = session.base_count + len(session.resources)
        current = cdemu.number_of_devices()
        if current != expected_without_pending:
            raise CDEmuOwnershipError(
                "Recovery CDEmu sospeso: journal contiene AddDevice pending e il count indica un device extra; "
                "ownership insufficiente per rimuoverlo automaticamente."
            )
        session = store.clear_pending_if_no_device(current)

    if session.removing_index is not None:
        expected_before = session.base_count + len(session.resources)
        current = cdemu.number_of_devices()
        if current == expected_before - 1:
            session = store.commit_removed(session.removing_index)
        elif current != expected_before:
            raise CDEmuOwnershipError(
                f"Recovery CDEmu ambiguo durante rimozione #{session.removing_index}: count={current}, "
                f"atteso {expected_before} o {expected_before - 1}."
            )

    if not session.resources:
        store.clear()
        return CleanupResult(True, False, ("journal CDEmu senza risorse residue: ripulito",))

    _validate_suffix(session, cdemu, mount_info, validate_optical)
    store.mark_cleanup()
    messages: list[str] = []
    while True:
        session = store.load()
        if session is None or not session.resources:
            break
        resource = session.resources[-1]
        expected_count = session.base_count + len(session.resources)
        if cdemu.number_of_devices() != expected_count or resource.index != expected_count - 1:
            raise CDEmuOwnershipError("Cleanup CDEmu interrotto: il suffisso non è più quello atteso.")
        loaded, _files, target, _ro = _validate_resource(resource, cdemu, mount_info, validate_optical)
        if target:
            unmount(resource.sr)
            after_target, _ = mount_info(resource.sr)
            if after_target:
                raise CDEmuOwnershipError(f"Device #{resource.index}: unmount non confermato ({after_target}).")
        if loaded:
            cdemu.unload(resource.index)
            loaded2, files2 = cdemu.wait_loaded(resource.index, False)
            if loaded2 or files2:
                raise CDEmuOwnershipError(f"Device #{resource.index}: unload non confermato.")
        mapped_sr, mapped_sg = cdemu.mapping(resource.index)
        if mapped_sr != resource.sr or (resource.sg and mapped_sg != resource.sg):
            raise CDEmuOwnershipError(f"Device #{resource.index}: mapping cambiato prima di RemoveDevice.")
        if block_rdev(resource.sr) != resource.rdev:
            raise CDEmuOwnershipError(f"Device #{resource.index}: rdev cambiato prima di RemoveDevice.")
        if cdemu.number_of_devices() != expected_count:
            raise CDEmuOwnershipError("Device count cambiato immediatamente prima di RemoveDevice.")
        store.set_removing(resource.index)
        cdemu.remove_last_device()
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            current = cdemu.number_of_devices()
            if current == expected_count - 1:
                break
            if current != expected_count:
                raise CDEmuOwnershipError(f"Count CDEmu inatteso dopo RemoveDevice: {current}, atteso {expected_count - 1}.")
            time.sleep(0.05)
        else:
            raise CDEmuOwnershipError("Timeout confermando RemoveDevice CDEmu.")
        store.commit_removed(resource.index)
        messages.append(f"device CDEmu owned #{resource.index} rimosso con ownership verificata")
    store.clear()
    return CleanupResult(True, False, tuple(messages or ["cleanup CDEmu completato"]))


__all__ = [
    "CDEmuOwnershipBusy", "CDEmuOwnershipError", "CDEmuOwnershipStore", "CleanupResult",
    "OwnedDevice", "OwnershipSession", "PendingDevice", "block_rdev", "cleanup_owned_session",
    "host_boot_id", "process_start_ticks", "session_owner_alive",
]
