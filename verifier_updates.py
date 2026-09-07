#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import hashlib
import io
import os
import re
import shutil
import sqlite3
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Callable

from verifier_common import (
    MAX_ARCHIVE_MEMBERS, MAX_DOWNLOAD_BYTES, MAX_MEMBER_BYTES,
    MAX_TOTAL_UNPACKED_BYTES, OFFICIAL_UPDATE_HOSTS, REDUMP_PC_URL,
    TOSEC_DOWNLOADS_URL, TOSEC_DOWNLOAD_RE, TOSEC_FALLBACK_URL, TOSEC_ZIP_RE,
    UpdateError, UpdateReport, VerificationError, _ensure_private_dir,
    _safe_catalog_source, verifier_data_dir,
)
from verifier_catalog import CatalogIndex

class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, allowed_hosts: frozenset[str]):
        super().__init__()
        self.allowed_hosts = allowed_hosts

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        _validate_update_url(newurl, self.allowed_hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _validate_update_url(url: str, allowed_hosts: frozenset[str] = OFFICIAL_UPDATE_HOSTS) -> str:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() != "https":
        raise UpdateError(f"Updater rifiuta URL non HTTPS: {url}")
    if host not in allowed_hosts:
        raise UpdateError(f"Updater rifiuta host non autorizzato: {host or '<vuoto>'}")
    if parsed.username or parsed.password:
        raise UpdateError("Updater rifiuta credenziali nell'URL.")
    return url


def _download_bytes(
    url: str,
    *,
    allowed_hosts: frozenset[str] = OFFICIAL_UPDATE_HOSTS,
    max_bytes: int = MAX_DOWNLOAD_BYTES,
    opener: urllib.request.OpenerDirector | None = None,
) -> tuple[bytes, str]:
    _validate_update_url(url, allowed_hosts)
    opener = opener or urllib.request.build_opener(_SafeRedirect(allowed_hosts))
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "BottlesRetroCD-Verifier/0.4 (+https://github.com/Paolo86cripple/bottles-retrocd)"},
    )
    try:
        response = opener.open(request, timeout=45)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Download DAT fallito: {url}: {exc}") from exc
    with response:
        final_url = response.geturl()
        _validate_update_url(final_url, allowed_hosts)
        length = response.headers.get("Content-Length")
        if length:
            try:
                declared = int(length)
            except ValueError:
                declared = 0
            if declared > max_bytes:
                raise UpdateError(f"Download DAT troppo grande: {declared} byte")
        out = bytearray()
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            out.extend(chunk)
            if len(out) > max_bytes:
                raise UpdateError(f"Download DAT supera il limite di {max_bytes} byte")
        return bytes(out), final_url


def resolve_latest_tosec_url(fetcher: Callable[[str], tuple[bytes, str]] | None = None) -> str:
    fetcher = fetcher or (lambda url: _download_bytes(url))
    try:
        page, final = fetcher(TOSEC_DOWNLOADS_URL)
        text = page.decode("utf-8", errors="replace")
        candidates: list[str] = []
        for regex in (TOSEC_ZIP_RE, TOSEC_DOWNLOAD_RE):
            for match in regex.finditer(text):
                href = match.group("href").replace("&amp;", "&")
                candidates.append(urllib.parse.urljoin(final, href))
            if candidates:
                break
        if candidates:
            # The official page is ordered newest first. Preserve page order.
            return _validate_update_url(candidates[0])
    except UpdateError:
        pass
    return TOSEC_FALLBACK_URL


def _safe_zip_members(zf: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = zf.infolist()
    if len(infos) > MAX_ARCHIVE_MEMBERS:
        raise UpdateError(f"Archivio DAT con troppi membri: {len(infos)}")
    total = 0
    accepted: list[zipfile.ZipInfo] = []
    for info in infos:
        name = info.filename.replace("\\", "/")
        pure = PurePosixPath(name)
        if not name or name.startswith("/") or ".." in pure.parts:
            raise UpdateError(f"ZIP traversal rifiutato: {info.filename!r}")
        # Unix symlink mode in the high 16 bits.
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise UpdateError(f"Symlink ZIP rifiutato: {info.filename!r}")
        if info.file_size > MAX_MEMBER_BYTES:
            raise UpdateError(f"Membro DAT troppo grande: {info.filename}")
        total += info.file_size
        if total > MAX_TOTAL_UNPACKED_BYTES:
            raise UpdateError("Archivio DAT supera il limite totale decompresso.")
        if not info.is_dir() and pure.suffix.lower() in {".dat", ".xml"}:
            accepted.append(info)
    if not accepted:
        raise UpdateError("Archivio ufficiale non contiene DAT/XML utilizzabili.")
    return accepted


def _materialise_dat_payload(payload: bytes, destination: Path, source: str) -> int:
    _ensure_private_dir(destination)
    if payload.startswith(b"PK\x03\x04") or payload.startswith(b"PK\x05\x06"):
        with zipfile.ZipFile(io.BytesIO(payload)) as zf:
            members = _safe_zip_members(zf)
            count = 0
            used: set[str] = set()
            for info in members:
                pure = PurePosixPath(info.filename.replace("\\", "/"))
                # Flatten into a deterministic source directory. Prefix a short
                # path digest only when basenames collide.
                name = pure.name
                if name in used:
                    digest = hashlib.sha256(str(pure).encode()).hexdigest()[:10]
                    name = f"{digest}-{name}"
                used.add(name)
                target = destination / name
                with zf.open(info, "r") as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024)
                os.chmod(target, 0o600)
                count += 1
            return count
    # Raw Redump response is normally Logiqx XML/DAT.
    if b"<datafile" not in payload[:1024 * 1024].lower():
        raise UpdateError("Payload DAT non riconosciuto come ZIP o XML Logiqx.")
    target = destination / f"{source}.dat"
    target.write_bytes(payload)
    os.chmod(target, 0o600)
    return 1


def _copy_sources_except(root: Path, excluded: str, stage_root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    if not root.exists():
        return result
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith(".") or child.name == excluded:
            continue
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", child.name):
            result[child.name] = child
    return result


def update_official_source(
    source: str,
    *,
    url: str | None = None,
    data_root: Path | None = None,
    catalog: CatalogIndex | None = None,
    downloader: Callable[[str], tuple[bytes, str]] | None = None,
) -> UpdateReport:
    """Download, validate and atomically install one official DAT source.

    The currently installed source directory and catalog DB are left untouched
    until the staged DATs have parsed successfully into a staged SQLite index.
    If any post-swap operation fails, the old source directory and catalog are
    restored before the exception is re-raised.
    """
    source = _safe_catalog_source(source)
    if source not in {"redump", "tosec"}:
        raise UpdateError(f"Sorgente ufficiale non supportata: {source}")
    data_root = data_root or verifier_data_dir()
    _ensure_private_dir(data_root)
    catalog = catalog or CatalogIndex(data_root / "catalog.sqlite3")
    downloader = downloader or (lambda value: _download_bytes(value))
    if url is None:
        url = REDUMP_PC_URL if source == "redump" else resolve_latest_tosec_url(downloader)
    _validate_update_url(url)

    payload, final_url = downloader(url)
    _validate_update_url(final_url)

    staging_parent = Path(tempfile.mkdtemp(prefix=f".{source}-update-", dir=data_root))
    staged_source = staging_parent / source
    staged_catalog = staging_parent / "catalog.sqlite3"
    live_source = data_root / source
    live_catalog = catalog.path
    backup_source = data_root / f".{source}.rollback"
    backup_catalog = data_root / ".catalog.sqlite3.rollback"
    swapped_source = swapped_catalog = False
    try:
        dat_count = _materialise_dat_payload(payload, staged_source, source)
        stage_index = CatalogIndex(staged_catalog, cache=catalog.cache)
        source_dirs = _copy_sources_except(data_root, source, staging_parent)
        source_dirs[source] = staged_source
        catalogs, games, roms = stage_index.rebuild(source_dirs)
        if dat_count <= 0 or catalogs <= 0 or roms <= 0:
            raise UpdateError("Aggiornamento DAT staged non contiene record verificabili.")

        with contextlib.suppress(FileNotFoundError):
            if backup_source.is_dir():
                shutil.rmtree(backup_source)
            else:
                backup_source.unlink()
        with contextlib.suppress(FileNotFoundError):
            backup_catalog.unlink()

        if live_source.exists():
            os.replace(live_source, backup_source)
        os.replace(staged_source, live_source)
        swapped_source = True

        if live_catalog.exists():
            os.replace(live_catalog, backup_catalog)
        os.replace(staged_catalog, live_catalog)
        swapped_catalog = True
        os.chmod(live_catalog, 0o600)

        # Validate the actual installed DB, not just the staged connection.
        with contextlib.closing(sqlite3.connect(live_catalog)) as db:
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise UpdateError("Indice installato fallisce integrity_check.")
            installed_roms = db.execute("SELECT count(*) FROM roms").fetchone()[0]
            if installed_roms <= 0:
                raise UpdateError("Indice installato è vuoto.")

        if backup_source.exists():
            shutil.rmtree(backup_source)
        with contextlib.suppress(FileNotFoundError):
            backup_catalog.unlink()
        return UpdateReport(source, final_url, dat_count, games, roms, live_catalog)
    except Exception:
        # Restore the previous valid generation even if the failure happens
        # in the narrow window after moving a live path to its rollback name
        # but before staging has been installed at the live path.
        if swapped_catalog or backup_catalog.exists():
            with contextlib.suppress(FileNotFoundError):
                live_catalog.unlink()
            if backup_catalog.exists():
                os.replace(backup_catalog, live_catalog)
        if swapped_source or backup_source.exists():
            if live_source.exists():
                shutil.rmtree(live_source)
            if backup_source.exists():
                os.replace(backup_source, live_source)
        raise
    finally:
        shutil.rmtree(staging_parent, ignore_errors=True)


def import_dat_directory(
    source: str,
    directory: Path,
    *,
    data_root: Path | None = None,
    catalog: CatalogIndex | None = None,
) -> UpdateReport:
    """Safely import user-provided DAT/XML files without touching originals."""
    source = _safe_catalog_source(source)
    directory = directory.expanduser().resolve(strict=True)
    if not directory.is_dir():
        raise VerificationError(f"Directory DAT non valida: {directory}")
    data_root = data_root or verifier_data_dir()
    _ensure_private_dir(data_root)
    catalog = catalog or CatalogIndex(data_root / "catalog.sqlite3")

    staging = Path(tempfile.mkdtemp(prefix=f".{source}-import-", dir=data_root))
    staged_source = staging / source
    _ensure_private_dir(staged_source)
    count = 0
    try:
        for path in sorted(directory.rglob("*"), key=lambda p: str(p).casefold()):
            if not path.is_file() or path.suffix.lower() not in {".dat", ".xml"}:
                continue
            target = staged_source / path.name
            if target.exists():
                digest = hashlib.sha256(str(path).encode()).hexdigest()[:10]
                target = staged_source / f"{digest}-{path.name}"
            shutil.copyfile(path, target)
            os.chmod(target, 0o600)
            count += 1
        if count == 0:
            raise VerificationError("Nessun DAT/XML trovato nella directory selezionata.")

        stage_catalog = staging / "catalog.sqlite3"
        stage_index = CatalogIndex(stage_catalog, cache=catalog.cache)
        dirs = _copy_sources_except(data_root, source, staging)
        dirs[source] = staged_source
        catalogs, games, roms = stage_index.rebuild(dirs)
        if catalogs <= 0 or roms <= 0:
            raise VerificationError("Import DAT privo di record verificabili.")

        live_source = data_root / source
        backup_source = data_root / f".{source}.rollback"
        backup_catalog = data_root / ".catalog.sqlite3.rollback"
        with contextlib.suppress(FileNotFoundError):
            if backup_source.is_dir():
                shutil.rmtree(backup_source)
            else:
                backup_source.unlink()
        with contextlib.suppress(FileNotFoundError):
            backup_catalog.unlink()
        swapped_source = swapped_catalog = False
        try:
            if live_source.exists():
                os.replace(live_source, backup_source)
            os.replace(staged_source, live_source)
            swapped_source = True
            if catalog.path.exists():
                os.replace(catalog.path, backup_catalog)
            os.replace(stage_catalog, catalog.path)
            swapped_catalog = True
            os.chmod(catalog.path, 0o600)
            if backup_source.exists():
                shutil.rmtree(backup_source)
            with contextlib.suppress(FileNotFoundError):
                backup_catalog.unlink()
        except Exception:
            if swapped_catalog or backup_catalog.exists():
                with contextlib.suppress(FileNotFoundError):
                    catalog.path.unlink()
                if backup_catalog.exists():
                    os.replace(backup_catalog, catalog.path)
            if swapped_source or backup_source.exists():
                if live_source.exists():
                    shutil.rmtree(live_source)
                if backup_source.exists():
                    os.replace(backup_source, live_source)
            raise
        return UpdateReport(source, str(directory), count, games, roms, catalog.path)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
