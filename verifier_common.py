#!/usr/bin/env python3
"""Redump/TOSEC verification backend for Bottles Retro CD.

Design goals:
- never modify optical dumps;
- never mount or execute image contents;
- parse large Logiqx XML DATs incrementally;
- use a persistent SQLite catalog and an independent file-hash cache;
- hash files in streaming mode (CRC32, MD5 and SHA-1 in one pass);
- reject CUE references escaping the authorised archive root;
- update official DAT sources over HTTPS with redirect/host allow-lists;
- stage, validate and index updates before atomically replacing live data.
"""
from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path


APP_DIRNAME = "bottles-retro-cd"
CATALOG_SCHEMA = 2
HASH_CACHE_SCHEMA = 1
HASH_CHUNK_SIZE = 8 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 1024 * 1024 * 1024  # 1 GiB compressed hard ceiling
MAX_ARCHIVE_MEMBERS = 20_000
MAX_MEMBER_BYTES = 256 * 1024 * 1024
MAX_TOTAL_UNPACKED_BYTES = 2 * 1024 * 1024 * 1024

REDUMP_PC_URL = "https://redump.org/datfile/pc/"
TOSEC_DOWNLOADS_URL = "https://www.tosecdev.org/downloads"
# Current official TOSEC complete pack visible from the project's own downloads page.
# The resolver below prefers the latest official link discovered at runtime.
TOSEC_FALLBACK_URL = (
    "https://www.tosecdev.org/downloads/category/59-2025-03-13"
    "?download=117%3Atosec-dat-pack-complete-4743-tosec-v2025-03-13"
)
OFFICIAL_UPDATE_HOSTS = frozenset({
    "redump.org",
    "www.redump.org",
    "tosecdev.org",
    "www.tosecdev.org",
})

CUE_FILE_RE = re.compile(
    r'^\s*FILE\s+(?:"(?P<quoted>[^"]+)"|(?P<bare>\S+))\s+\S+', re.IGNORECASE
)
TOC_FILE_RE = re.compile(
    r'^\s*(?:FILE|DATAFILE|AUDIOFILE)\s+(?:"(?P<quoted>[^"]+)"|(?P<bare>\S+))',
    re.IGNORECASE,
)
TOSEC_DOWNLOAD_RE = re.compile(
    r'href=["\'](?P<href>[^"\']*download=[^"\']+)["\'][^>]*>\s*(?:Download|TOSEC\s*-\s*DAT\s*Pack)',
    re.IGNORECASE,
)
TOSEC_ZIP_RE = re.compile(
    r'href=["\'](?P<href>[^"\']*download=[^"\']+)["\'][^>]*>[^<]*TOSEC[^<]*DAT\s*Pack[^<]*Complete',
    re.IGNORECASE,
)


def _xdg_data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))


def _xdg_cache_home() -> Path:
    return Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))


def verifier_data_dir() -> Path:
    return _xdg_data_home() / APP_DIRNAME / "verifier"


def verifier_cache_dir() -> Path:
    return _xdg_cache_home() / APP_DIRNAME / "verifier"


@dataclass(frozen=True, slots=True)
class FileHash:
    path: Path
    size: int
    crc32: str
    md5: str
    sha1: str
    cached: bool = False

    @property
    def fingerprint(self) -> tuple[int, str, str, str]:
        return self.size, self.crc32, self.md5, self.sha1


@dataclass(frozen=True, slots=True)
class CatalogMatch:
    source: str
    catalog: str
    game_name: str
    description: str
    serial: str
    version: str
    protection: str
    game_id: int


@dataclass(frozen=True, slots=True)
class FileMatch:
    file: FileHash
    candidates: tuple[CatalogMatch, ...]


@dataclass(frozen=True, slots=True)
class VerificationResult:
    descriptor: Path
    payloads: tuple[FileHash, ...]
    status: str
    exact_matches: tuple[CatalogMatch, ...]
    file_matches: tuple[FileMatch, ...]
    detail: str = ""

    @property
    def matched(self) -> bool:
        return self.status == "MATCH" and len(self.exact_matches) == 1


@dataclass(frozen=True, slots=True)
class SetVerificationResult:
    results: tuple[VerificationResult, ...]

    @property
    def status(self) -> str:
        if self.results and all(item.matched for item in self.results):
            return "MATCH"
        if any(item.status == "AMBIGUOUS" for item in self.results):
            return "AMBIGUOUS"
        return "MISMATCH"


@dataclass(frozen=True, slots=True)
class UpdateReport:
    source: str
    url: str
    dat_files: int
    games: int
    roms: int
    catalog_path: Path


class VerificationError(RuntimeError):
    pass


class UpdateError(VerificationError):
    pass


def _ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def _strip_ns(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _child_text(node: ET.Element, *names: str) -> str:
    wanted = {name.lower() for name in names}
    for child in node:
        if _strip_ns(child.tag) in wanted:
            return (child.text or "").strip()
    return ""


def _normalise_hex(value: str | None, digits: int) -> str:
    if not value:
        return ""
    raw = re.sub(r"[^0-9a-fA-F]", "", value).lower()
    if len(raw) != digits:
        return ""
    return raw


def _normalise_size(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        size = int(value)
    except (TypeError, ValueError):
        return None
    return size if size >= 0 else None


def _safe_catalog_source(source: str) -> str:
    source = source.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", source):
        raise VerificationError(f"Nome sorgente DAT non valido: {source!r}")
    return source


def _validate_under(path: Path, root: Path, *, must_exist: bool = True) -> Path:
    try:
        resolved = path.expanduser().resolve(strict=must_exist)
    except OSError as exc:
        raise VerificationError(f"Percorso non accessibile: {path}: {exc}") from exc
    root_r = root.expanduser().resolve(strict=False)
    if not resolved.is_relative_to(root_r):
        raise VerificationError(f"Percorso fuori dalla radice autorizzata: {resolved}")
    return resolved


def _descriptor_reference(base: Path, token: str, root: Path) -> Path:
    if "\x00" in token:
        raise VerificationError("Riferimento descriptor contenente NUL rifiutato.")
    token = token.replace("\\", os.sep)
    # Windows absolute paths must not silently become relative on Linux.
    if re.match(r"^[A-Za-z]:[\\/]", token) or token.startswith(("//", "\\\\")):
        raise VerificationError(f"Riferimento assoluto nel descriptor rifiutato: {token}")
    p = Path(token)
    if p.is_absolute():
        raise VerificationError(f"Riferimento assoluto nel descriptor rifiutato: {token}")
    resolved = _validate_under(base / p, root, must_exist=True)
    if not resolved.is_file():
        raise VerificationError(f"Payload descriptor non è un file: {resolved}")
    return resolved


def parse_cue_payloads(cue: Path, root: Path | None = None) -> tuple[Path, ...]:
    cue = cue.expanduser().resolve(strict=True)
    root = (root or cue.parent).expanduser().resolve(strict=False)
    _validate_under(cue, root)
    try:
        text = cue.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = cue.read_text(encoding="latin-1")
    seen: set[Path] = set()
    result: list[Path] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        match = CUE_FILE_RE.match(line)
        if not match:
            continue
        token = match.group("quoted") or match.group("bare") or ""
        try:
            payload = _descriptor_reference(cue.parent, token, root)
        except VerificationError as exc:
            raise VerificationError(f"CUE {cue.name}:{lineno}: {exc}") from exc
        if payload not in seen:
            seen.add(payload)
            result.append(payload)
    if not result:
        raise VerificationError(f"CUE senza FILE valido: {cue}")
    return tuple(result)


def parse_toc_payloads(toc: Path, root: Path | None = None) -> tuple[Path, ...]:
    toc = toc.expanduser().resolve(strict=True)
    root = (root or toc.parent).expanduser().resolve(strict=False)
    _validate_under(toc, root)
    try:
        text = toc.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        text = toc.read_text(encoding="latin-1")
    seen: set[Path] = set()
    result: list[Path] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        match = TOC_FILE_RE.match(line)
        if not match:
            continue
        token = match.group("quoted") or match.group("bare") or ""
        try:
            payload = _descriptor_reference(toc.parent, token, root)
        except VerificationError as exc:
            raise VerificationError(f"TOC {toc.name}:{lineno}: {exc}") from exc
        if payload not in seen:
            seen.add(payload)
            result.append(payload)
    if not result:
        raise VerificationError(f"TOC senza FILE/DATAFILE/AUDIOFILE valido: {toc}")
    return tuple(result)


def descriptor_payloads(descriptor: Path, root: Path | None = None) -> tuple[Path, ...]:
    descriptor = descriptor.expanduser().resolve(strict=True)
    root = (root or descriptor.parent).expanduser().resolve(strict=False)
    descriptor = _validate_under(descriptor, root)
    suffix = descriptor.suffix.lower()
    if suffix == ".cue":
        return parse_cue_payloads(descriptor, root)
    if suffix == ".toc":
        return parse_toc_payloads(descriptor, root)
    companions: dict[str, tuple[str, ...]] = {
        ".ccd": (".img",),
        ".mds": (".mdf",),
        ".b5t": (".b5i", ".b5i".upper()),
        ".b6t": (".b6i", ".b6i".upper()),
    }
    if suffix in companions:
        for ext in companions[suffix]:
            candidate = descriptor.with_suffix(ext)
            if candidate.exists():
                return (_validate_under(candidate, root),)
        raise VerificationError(f"Descriptor {descriptor.name}: payload associato non trovato.")
    return (descriptor,)
