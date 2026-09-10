#!/usr/bin/env python3
"""Dedicated bubblewrap boundary for archive verification and protection scans.

The game sandbox is intentionally not involved here. This module launches a
small verifier worker in a separate bubblewrap sandbox with:

- no host network namespace;
- no host HOME;
- a private /tmp and minimal /dev;
- the application code and authorised archive mounted read-only;
- the verifier catalog mounted read-only;
- only the verifier hash-cache mounted read-write.

Official DAT updates/imports remain outside this boundary for now and are a
separate 0.4.1 hardening step.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from verifier_common import verifier_cache_dir, verifier_data_dir


_ALLOWED_OPERATIONS = frozenset({"verify", "verify-set", "scan", "verify-scan"})


class VerifierSandboxError(RuntimeError):
    """Raised when the dedicated verifier boundary cannot be proven/used."""


@dataclass(frozen=True, slots=True)
class SandboxResponse:
    text: str
    status: str
    matched: bool | None = None


@dataclass(frozen=True, slots=True)
class SandboxAttestation:
    archive_read_only: bool
    app_read_only: bool
    catalog_read_only: bool | None
    cache_writable: bool
    home_sentinel_hidden: bool | None
    interfaces: tuple[str, ...]
    proc_hidden: bool
    sys_hidden: bool
    run_hidden: bool

    @property
    def ok(self) -> bool:
        catalog_ok = self.catalog_read_only is not False
        sentinel_ok = self.home_sentinel_hidden is not False
        return (
            self.archive_read_only
            and self.app_read_only
            and catalog_ok
            and self.cache_writable
            and sentinel_ok
            and set(self.interfaces).issubset({"lo"})
            and self.proc_hidden
            and self.sys_hidden
            and self.run_hidden
        )

    def format(self) -> str:
        catalog = "absent" if self.catalog_read_only is None else ("RO" if self.catalog_read_only else "RW")
        home = "not-probed" if self.home_sentinel_hidden is None else ("hidden" if self.home_sentinel_hidden else "VISIBLE")
        interfaces = ",".join(self.interfaces) if self.interfaces else "none"
        status = "PASS" if self.ok else "FAIL"
        return (
            f"[{status}] Verifier sandbox: archive={'RO' if self.archive_read_only else 'RW'} · "
            f"app={'RO' if self.app_read_only else 'RW'} · catalog={catalog} · "
            f"cache={'RW' if self.cache_writable else 'non-RW'} · host-home-sentinel={home} · "
            f"net={interfaces} · proc={'hidden' if self.proc_hidden else 'visible'} · "
            f"sys={'hidden' if self.sys_hidden else 'visible'} · "
            f"run-host={'hidden' if self.run_hidden else 'VISIBLE'}"
        )


def _private_dir(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        resolved = path.resolve(strict=True)
        info = resolved.stat()
    except OSError as exc:
        raise VerifierSandboxError(f"Cache verifier privata non preparabile: {path}: {exc}") from exc
    if not resolved.is_dir():
        raise VerifierSandboxError(f"Cache verifier non è una directory: {resolved}")
    if info.st_uid != os.getuid():
        raise VerifierSandboxError(f"Cache verifier non appartiene all'utente corrente: {resolved}")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise VerifierSandboxError(f"Cache verifier non privata (richiesto 0700): {resolved}")
    return resolved


def _canonical_archive(root: Path) -> Path:
    try:
        resolved = root.expanduser().resolve(strict=True)
    except OSError as exc:
        raise VerifierSandboxError(f"Archivio verifier non accessibile: {root}: {exc}") from exc
    if not resolved.is_dir():
        raise VerifierSandboxError(f"Archivio verifier non è una directory: {resolved}")
    return resolved


def _canonical_inputs(paths: Iterable[Path], root: Path) -> tuple[Path, ...]:
    result: list[Path] = []
    for path in paths:
        try:
            resolved = path.expanduser().resolve(strict=True)
        except OSError as exc:
            raise VerifierSandboxError(f"Input verifier non accessibile: {path}: {exc}") from exc
        if not resolved.is_file():
            raise VerifierSandboxError(f"Input verifier non è un file: {resolved}")
        if not resolved.is_relative_to(root):
            raise VerifierSandboxError(f"Input verifier fuori dall'archivio autorizzato: {resolved}")
        result.append(resolved)
    if not result:
        raise VerifierSandboxError("Nessun input verifier specificato.")
    return tuple(result)


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _validate_mount_layout(*, archive: Path, app_dir: Path, data_dir: Path, cache_dir: Path) -> None:
    """Ensure the sole RW bind cannot punch a writable hole into trusted/RO trees."""
    protected = {
        "archivio": archive,
        "codice applicazione": app_dir,
        "catalogo verifier": data_dir,
    }
    for label, path in protected.items():
        if _overlaps(cache_dir, path):
            raise VerifierSandboxError(
                f"Layout verifier rifiutato: cache RW sovrapposta a {label} ({cache_dir} ↔ {path})."
            )
    if _overlaps(archive, app_dir):
        raise VerifierSandboxError(
            f"Layout verifier rifiutato: archivio e codice applicazione si sovrappongono ({archive} ↔ {app_dir})."
        )
    if _overlaps(archive, data_dir):
        raise VerifierSandboxError(
            f"Layout verifier rifiutato: archivio e catalogo verifier si sovrappongono ({archive} ↔ {data_dir})."
        )


def _sandbox_command(
    root: Path,
    *,
    bwrap: str,
    app_dir: Path,
    data_dir: Path,
    cache_dir: Path,
) -> tuple[str, ...]:
    """Build the exact no-network, least-filesystem bubblewrap invocation."""
    worker = app_dir / "verifier_worker.py"
    if not worker.is_file():
        raise VerifierSandboxError(f"Worker verifier mancante: {worker}")

    data_home = data_dir.parent.parent
    cache_home = cache_dir.parent.parent

    args: list[str] = [
        bwrap,
        "--unshare-all",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        "--ro-bind", "/usr", "/usr",
        # Arch's dynamic linker is reached through the root-level /lib and
        # /lib64 compatibility symlinks. A bwrap root starts empty, so recreate
        # those links explicitly instead of exposing any additional host tree.
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib", "/lib64",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
    ]

    # Installed code is already covered by the /usr RO mount. Development
    # checkouts live elsewhere and receive one exact read-only bind.
    app_in_usr = app_dir.is_relative_to(Path("/usr"))
    if not app_in_usr:
        args.extend(("--ro-bind", str(app_dir), str(app_dir)))

    args.extend(("--ro-bind", str(root), str(root)))

    # The catalog is trusted application state for read operations and never
    # needs to be writable in this worker. An absent catalog is represented by
    # an absent bind and correctly yields NO_INDEX.
    if data_dir.is_dir():
        args.extend(("--ro-bind", str(data_dir), str(data_dir)))

    # Hashing may update only the dedicated verifier cache.
    args.extend(("--bind", str(cache_dir), str(cache_dir)))

    args.extend(
        (
            "--setenv", "HOME", "/tmp/retrocd-home",
            "--setenv", "XDG_DATA_HOME", str(data_home),
            "--setenv", "XDG_CACHE_HOME", str(cache_home),
            "--setenv", "TMPDIR", "/tmp",
            "--setenv", "PATH", "/usr/bin",
            "--setenv", "LANG", "C.UTF-8",
            "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
            "--setenv", "PYTHONNOUSERSITE", "1",
            "--setenv", "RETROCD_VERIFIER_SANDBOX", "1",
            "--dir", "/tmp/retrocd-home",
            "--chdir", str(app_dir),
            "--",
            "/usr/bin/python3",
            "-B",
            "-s",
            str(worker),
        )
    )
    return tuple(args)


def _trusted_bwrap(path: str) -> str:
    try:
        resolved = Path(path).resolve(strict=True)
        info = resolved.stat()
    except OSError as exc:
        raise VerifierSandboxError(f"Eseguibile bwrap non verificabile: {path}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or not os.access(resolved, os.X_OK):
        raise VerifierSandboxError(f"Eseguibile bwrap non valido: {resolved}")
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise VerifierSandboxError(
            f"Eseguibile bwrap non trusted: {resolved} deve essere root-owned e non scrivibile da group/other."
        )
    return str(resolved)


def _host_home_sentinel(mounted: tuple[Path, ...]) -> Path | None:
    """Choose an existing host-HOME path that is not intentionally mounted."""
    try:
        home = Path.home().resolve(strict=True)
    except OSError:
        return None
    candidates = (
        home / ".config",
        home / ".ssh",
        home / ".local" / "share" / "bubblejail",
    )
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if any(_overlaps(resolved, item) for item in mounted):
            continue
        return resolved
    return None


def _host_run_sentinels(mounted: tuple[Path, ...]) -> tuple[Path, ...]:
    """Pick real host runtime paths that must stay absent from the worker.

    `/run` itself may legitimately exist as a synthetic parent when an exact
    authorised bind lives below `/run/media`.  What must never appear is host
    runtime state such as the user runtime directory, systemd, udev or D-Bus.
    """
    candidates = (
        Path(f"/run/user/{os.getuid()}"),
        Path("/run/systemd"),
        Path("/run/udev"),
        Path("/run/dbus"),
        Path("/run/NetworkManager"),
    )
    result: list[Path] = []
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if any(_overlaps(resolved, item) for item in mounted):
            continue
        result.append(resolved)
    return tuple(result)


_PROBE_SCRIPT = r'''
import json
import os
import socket
import sys
from pathlib import Path

req = json.load(sys.stdin)
readonly = getattr(os, "ST_RDONLY", 1)

def is_ro(path):
    return bool(os.statvfs(path).f_flag & readonly)

cache = Path(req["cache"])
probe = cache / (".retrocd-sandbox-probe-%d" % os.getpid())
cache_rw = False
try:
    probe.write_bytes(b"probe")
    cache_rw = probe.read_bytes() == b"probe"
finally:
    try:
        probe.unlink()
    except FileNotFoundError:
        pass

sentinel = req.get("home_sentinel")
run_sentinels = req.get("run_sentinels") or []
result = {
    "archive_read_only": is_ro(req["archive"]),
    "app_read_only": is_ro(req["app"]),
    "catalog_read_only": is_ro(req["data"]) if req.get("data_present") else None,
    "cache_writable": cache_rw,
    "home_sentinel_hidden": (not Path(sentinel).exists()) if sentinel else None,
    "interfaces": sorted(name for _idx, name in socket.if_nameindex()),
    "proc_hidden": not Path("/proc").exists(),
    "sys_hidden": not Path("/sys").exists(),
    "run_hidden": bool(run_sentinels) and all(not Path(item).exists() for item in run_sentinels),
}
print(json.dumps(result, sort_keys=True))
'''


class VerifierSandbox:
    """Client for read-only archive operations executed in the worker sandbox."""

    def __init__(self, *, bwrap_path: str | None = None):
        self._bwrap_path = bwrap_path

    def _bwrap(self) -> str:
        path = self._bwrap_path or shutil.which("bwrap")
        if not path:
            raise VerifierSandboxError(
                "Sandbox verifier non disponibile: manca 'bwrap' (pacchetto bubblewrap). "
                "La verifica viene rifiutata invece di eseguire parser di immagini sul processo host."
            )
        return _trusted_bwrap(path)

    def _layout(self, root: Path) -> tuple[Path, Path, Path, Path]:
        archive = _canonical_archive(root)
        app_dir = Path(__file__).resolve(strict=True).parent
        data_dir = verifier_data_dir().expanduser().resolve(strict=False)
        cache_candidate = verifier_cache_dir().expanduser().resolve(strict=False)

        # Validate before mkdir/chmod so even a hostile/custom XDG_CACHE_HOME
        # cannot make the launcher create a directory inside the archive.
        _validate_mount_layout(
            archive=archive,
            app_dir=app_dir,
            data_dir=data_dir,
            cache_dir=cache_candidate,
        )
        cache_dir = _private_dir(cache_candidate)
        _validate_mount_layout(
            archive=archive,
            app_dir=app_dir,
            data_dir=data_dir,
            cache_dir=cache_dir,
        )
        return archive, app_dir, data_dir, cache_dir

    def attest(self, root: Path, *, timeout: float = 10.0) -> SandboxAttestation:
        """Execute a non-destructive proof of the effective verifier boundary."""
        archive, app_dir, data_dir, cache_dir = self._layout(root)
        bwrap = self._bwrap()
        base = list(
            _sandbox_command(
                archive,
                bwrap=bwrap,
                app_dir=app_dir,
                data_dir=data_dir,
                cache_dir=cache_dir,
            )
        )
        separator = base.index("--")
        command = tuple(base[: separator + 1] + ["/usr/bin/python3", "-B", "-s", "-c", _PROBE_SCRIPT])
        data_present = data_dir.is_dir()
        mounted = (archive, app_dir, data_dir, cache_dir)
        sentinel = _host_home_sentinel(mounted)
        run_sentinels = _host_run_sentinels(mounted)
        request = {
            "archive": str(archive),
            "app": str(app_dir),
            "data": str(data_dir),
            "data_present": data_present,
            "cache": str(cache_dir),
            "home_sentinel": str(sentinel) if sentinel is not None else None,
            "run_sentinels": [str(path) for path in run_sentinels],
        }
        try:
            proc = subprocess.run(
                command,
                input=json.dumps(request),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout,
                close_fds=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise VerifierSandboxError("Attestation verifier sandbox terminata per timeout.") from exc
        except OSError as exc:
            raise VerifierSandboxError(f"Impossibile avviare attestation verifier sandbox: {exc}") from exc
        if proc.returncode != 0:
            details = (proc.stderr or proc.stdout).strip()[-4000:]
            raise VerifierSandboxError(
                f"Attestation verifier sandbox fallita con rc={proc.returncode}: {details}"
            )
        try:
            payload = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise VerifierSandboxError("Attestation verifier sandbox: risposta JSON non valida.") from exc
        try:
            result = SandboxAttestation(
                archive_read_only=payload["archive_read_only"] is True,
                app_read_only=payload["app_read_only"] is True,
                catalog_read_only=(
                    None if payload["catalog_read_only"] is None else payload["catalog_read_only"] is True
                ),
                cache_writable=payload["cache_writable"] is True,
                home_sentinel_hidden=(
                    None if payload["home_sentinel_hidden"] is None else payload["home_sentinel_hidden"] is True
                ),
                interfaces=tuple(str(item) for item in payload["interfaces"]),
                proc_hidden=payload["proc_hidden"] is True,
                sys_hidden=payload["sys_hidden"] is True,
                run_hidden=payload["run_hidden"] is True,
            )
        except (KeyError, TypeError) as exc:
            raise VerifierSandboxError("Attestation verifier sandbox: schema risposta non valido.") from exc
        if not result.ok:
            raise VerifierSandboxError(result.format())
        return result

    def run(
        self,
        operation: str,
        paths: Iterable[Path],
        root: Path,
        *,
        timeout: float | None = None,
    ) -> SandboxResponse:
        if operation not in _ALLOWED_OPERATIONS:
            raise VerifierSandboxError(f"Operazione verifier sandbox non consentita: {operation!r}")

        archive, app_dir, data_dir, cache_dir = self._layout(root)
        inputs = _canonical_inputs(paths, archive)

        command = _sandbox_command(
            archive,
            bwrap=self._bwrap(),
            app_dir=app_dir,
            data_dir=data_dir,
            cache_dir=cache_dir,
        )
        request = {
            "operation": operation,
            "root": str(archive),
            "paths": [str(path) for path in inputs],
        }
        try:
            proc = subprocess.run(
                command,
                input=json.dumps(request, ensure_ascii=False),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout,
                close_fds=True,
            )
        except subprocess.TimeoutExpired as exc:
            raise VerifierSandboxError("Verifier sandbox terminato per timeout.") from exc
        except OSError as exc:
            raise VerifierSandboxError(f"Impossibile avviare verifier sandbox: {exc}") from exc

        payload: object | None = None
        if proc.stdout.strip():
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError:
                payload = None

        if isinstance(payload, dict) and payload.get("ok") is False:
            error = str(payload.get("error") or "errore worker non specificato")
            raise VerifierSandboxError(f"Verifier sandbox: {error}")

        if proc.returncode != 0:
            details = (proc.stderr or proc.stdout).strip()[-4000:]
            suffix = f": {details}" if details else ""
            raise VerifierSandboxError(
                f"Verifier sandbox fallito con rc={proc.returncode}{suffix}"
            )

        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise VerifierSandboxError("Verifier sandbox: risposta worker non valida.")

        text = payload.get("text")
        status = payload.get("status")
        matched = payload.get("matched")
        if not isinstance(text, str) or not isinstance(status, str):
            raise VerifierSandboxError("Verifier sandbox: schema risposta worker non valido.")
        if matched is not None and not isinstance(matched, bool):
            raise VerifierSandboxError("Verifier sandbox: campo matched non valido.")
        return SandboxResponse(text=text, status=status, matched=matched)

    def verify(self, path: Path, root: Path) -> SandboxResponse:
        return self.run("verify", (path,), root)

    def verify_set(self, paths: Iterable[Path], root: Path) -> SandboxResponse:
        return self.run("verify-set", tuple(paths), root)

    def scan(self, path: Path, root: Path) -> SandboxResponse:
        return self.run("scan", (path,), root)

    def verify_scan(self, path: Path, root: Path) -> SandboxResponse:
        return self.run("verify-scan", (path,), root)
