#!/usr/bin/env python3
"""Dedicated bubblewrap boundary for official DAT updates.

The updater is intentionally separate from both the game sandbox and the
read-only verifier worker. It receives host networking only for official HTTPS
updates, while keeping host HOME and the configured game archive hidden.
Only the verifier data and cache directories are writable.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path
from typing import Iterable

from settings_backend import load_settings
from verifier_common import UpdateReport, verifier_cache_dir, verifier_data_dir


class VerifierUpdaterSandboxError(RuntimeError):
    """Raised when the official DAT updater boundary cannot be proven/used."""


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _private_dir(path: Path) -> Path:
    try:
        path.mkdir(parents=True, exist_ok=True)
        os.chmod(path, 0o700)
        resolved = path.resolve(strict=True)
        info = resolved.stat()
    except OSError as exc:
        raise VerifierUpdaterSandboxError(f"Directory updater privata non preparabile: {path}: {exc}") from exc
    if not resolved.is_dir():
        raise VerifierUpdaterSandboxError(f"Directory updater non è una directory: {resolved}")
    if info.st_uid != os.getuid():
        raise VerifierUpdaterSandboxError(f"Directory updater non appartiene all'utente corrente: {resolved}")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise VerifierUpdaterSandboxError(f"Directory updater non privata (richiesto 0700): {resolved}")
    return resolved


def _trusted_bwrap(path: str) -> str:
    try:
        resolved = Path(path).resolve(strict=True)
        info = resolved.stat()
    except OSError as exc:
        raise VerifierUpdaterSandboxError(f"Eseguibile bwrap non verificabile: {path}: {exc}") from exc
    if not stat.S_ISREG(info.st_mode) or not os.access(resolved, os.X_OK):
        raise VerifierUpdaterSandboxError(f"Eseguibile bwrap non valido: {resolved}")
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise VerifierUpdaterSandboxError(
            f"Eseguibile bwrap non trusted: {resolved} deve essere root-owned e non scrivibile da group/other."
        )
    return str(resolved)


def _configured_archive_root(explicit: Path | None = None) -> Path | None:
    if explicit is not None:
        return explicit.expanduser().resolve(strict=False)
    raw = load_settings().get("archive_root", "")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return Path(raw).expanduser().resolve(strict=False)


def _validate_layout(*, app_dir: Path, data_dir: Path, cache_dir: Path, archive: Path | None) -> None:
    if _overlaps(data_dir, app_dir) or _overlaps(cache_dir, app_dir):
        raise VerifierUpdaterSandboxError("Layout updater rifiutato: stato RW sovrapposto al codice applicazione.")
    if _overlaps(data_dir, cache_dir):
        raise VerifierUpdaterSandboxError("Layout updater rifiutato: data e cache RW si sovrappongono.")
    if archive is not None:
        if _overlaps(data_dir, archive) or _overlaps(cache_dir, archive):
            raise VerifierUpdaterSandboxError("Layout updater rifiutato: stato RW sovrapposto all'archivio giochi.")
        if _overlaps(app_dir, archive):
            raise VerifierUpdaterSandboxError("Layout updater rifiutato: codice applicazione sovrapposto all'archivio giochi.")


def _trusted_network_source(path: Path) -> Path | None:
    """Resolve one host TLS/DNS input and reject writable/untrusted sources."""
    try:
        resolved = path.resolve(strict=True)
        info = resolved.stat()
    except OSError:
        return None
    if info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o022:
        raise VerifierUpdaterSandboxError(f"Risorsa rete updater non trusted: {resolved}")
    if not (resolved.is_file() or resolved.is_dir()):
        raise VerifierUpdaterSandboxError(f"Risorsa rete updater non valida: {resolved}")
    return resolved


def _network_mounts() -> tuple[tuple[Path, Path], ...]:
    """Return exact RO host inputs needed by libc/OpenSSL for HTTPS and DNS."""
    destinations = (
        Path("/etc/resolv.conf"),
        Path("/etc/hosts"),
        Path("/etc/nsswitch.conf"),
        Path("/etc/gai.conf"),
        Path("/etc/ssl/cert.pem"),
        Path("/etc/ssl/certs"),
    )
    mounts: list[tuple[Path, Path]] = []
    for destination in destinations:
        source = _trusted_network_source(destination)
        if source is not None:
            mounts.append((source, destination))

    if not any(dest == Path("/etc/resolv.conf") for _src, dest in mounts):
        raise VerifierUpdaterSandboxError("Updater sandbox: /etc/resolv.conf trusted non disponibile.")
    if not any(dest in {Path("/etc/ssl/cert.pem"), Path("/etc/ssl/certs")} for _src, dest in mounts):
        raise VerifierUpdaterSandboxError("Updater sandbox: CA TLS trusted non disponibili.")
    return tuple(mounts)


def _sandbox_command(
    *,
    bwrap: str,
    app_dir: Path,
    data_dir: Path,
    cache_dir: Path,
    network_mounts: Iterable[tuple[Path, Path]],
) -> tuple[str, ...]:
    worker = app_dir / "verifier_updater_worker.py"
    if not worker.is_file():
        raise VerifierUpdaterSandboxError(f"Worker updater mancante: {worker}")

    data_home = data_dir.parent.parent
    cache_home = cache_dir.parent.parent
    args: list[str] = [
        bwrap,
        "--unshare-all",
        # Only this worker retains the host network namespace. All other
        # namespaces remain unshared. URL/redirect allow-lists are enforced by
        # verifier_updates.py inside the worker.
        "--share-net",
        "--die-with-parent",
        "--new-session",
        "--clearenv",
        "--ro-bind", "/usr", "/usr",
        "--symlink", "usr/lib", "/lib",
        "--symlink", "usr/lib", "/lib64",
        "--dev", "/dev",
        "--tmpfs", "/tmp",
    ]

    for source, destination in network_mounts:
        args.extend(("--ro-bind", str(source), str(destination)))

    if not app_dir.is_relative_to(Path("/usr")):
        args.extend(("--ro-bind", str(app_dir), str(app_dir)))

    args.extend(("--bind", str(data_dir), str(data_dir)))
    args.extend(("--bind", str(cache_dir), str(cache_dir)))

    env: list[str] = [
        "--setenv", "HOME", "/tmp/retrocd-updater-home",
        "--setenv", "XDG_DATA_HOME", str(data_home),
        "--setenv", "XDG_CACHE_HOME", str(cache_home),
        "--setenv", "TMPDIR", "/tmp",
        "--setenv", "PATH", "/usr/bin",
        "--setenv", "LANG", "C.UTF-8",
        "--setenv", "PYTHONDONTWRITEBYTECODE", "1",
        "--setenv", "PYTHONNOUSERSITE", "1",
        "--setenv", "RETROCD_UPDATER_SANDBOX", "1",
    ]
    destinations = {dest for _source, dest in network_mounts}
    if Path("/etc/ssl/cert.pem") in destinations:
        env.extend(("--setenv", "SSL_CERT_FILE", "/etc/ssl/cert.pem"))
    elif Path("/etc/ssl/certs") in destinations:
        env.extend(("--setenv", "SSL_CERT_DIR", "/etc/ssl/certs"))

    args.extend(env)
    args.extend(
        (
            "--dir", "/tmp/retrocd-updater-home",
            "--chdir", str(app_dir),
            "--",
            "/usr/bin/python3",
            "-B",
            "-s",
            str(worker),
        )
    )
    return tuple(args)


class VerifierUpdaterSandbox:
    def __init__(self, *, bwrap_path: str | None = None):
        self._bwrap_path = bwrap_path

    def _bwrap(self) -> str:
        path = self._bwrap_path or shutil.which("bwrap")
        if not path:
            raise VerifierUpdaterSandboxError(
                "Sandbox updater non disponibile: manca 'bwrap' (pacchetto bubblewrap)."
            )
        return _trusted_bwrap(path)

    def update(
        self,
        source: str,
        *,
        archive_root: Path | None = None,
        timeout: float | None = None,
    ) -> UpdateReport:
        if source not in {"redump", "tosec"}:
            raise VerifierUpdaterSandboxError(f"Sorgente updater non consentita: {source!r}")

        app_dir = Path(__file__).resolve(strict=True).parent
        data_candidate = verifier_data_dir().expanduser().resolve(strict=False)
        cache_candidate = verifier_cache_dir().expanduser().resolve(strict=False)
        archive = _configured_archive_root(archive_root)
        _validate_layout(app_dir=app_dir, data_dir=data_candidate, cache_dir=cache_candidate, archive=archive)
        data_dir = _private_dir(data_candidate)
        cache_dir = _private_dir(cache_candidate)
        _validate_layout(app_dir=app_dir, data_dir=data_dir, cache_dir=cache_dir, archive=archive)

        command = _sandbox_command(
            bwrap=self._bwrap(),
            app_dir=app_dir,
            data_dir=data_dir,
            cache_dir=cache_dir,
            network_mounts=_network_mounts(),
        )
        request = {
            "source": source,
            "forbidden_archive": str(archive) if archive is not None else None,
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
            raise VerifierUpdaterSandboxError("Updater sandbox terminato per timeout.") from exc
        except OSError as exc:
            raise VerifierUpdaterSandboxError(f"Impossibile avviare updater sandbox: {exc}") from exc

        payload: object | None = None
        if proc.stdout.strip():
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError:
                payload = None

        if isinstance(payload, dict) and payload.get("ok") is False:
            raise VerifierUpdaterSandboxError(f"Updater sandbox: {payload.get('error') or 'errore worker'}")
        if proc.returncode != 0:
            details = (proc.stderr or proc.stdout).strip()[-4000:]
            suffix = f": {details}" if details else ""
            raise VerifierUpdaterSandboxError(f"Updater sandbox fallito con rc={proc.returncode}{suffix}")
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise VerifierUpdaterSandboxError("Updater sandbox: risposta worker non valida.")

        try:
            report = UpdateReport(
                source=str(payload["source"]),
                url=str(payload["url"]),
                dat_files=int(payload["dat_files"]),
                games=int(payload["games"]),
                roms=int(payload["roms"]),
                catalog_path=Path(str(payload["catalog_path"])),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise VerifierUpdaterSandboxError("Updater sandbox: schema risposta worker non valido.") from exc
        if report.source != source or report.dat_files <= 0 or report.games < 0 or report.roms <= 0:
            raise VerifierUpdaterSandboxError("Updater sandbox: risultato semanticamente non valido.")
        if report.catalog_path.resolve(strict=False) != (data_dir / "catalog.sqlite3").resolve(strict=False):
            raise VerifierUpdaterSandboxError("Updater sandbox: catalog path inatteso.")
        return report
