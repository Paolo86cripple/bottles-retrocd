#!/usr/bin/env python3
"""Read-only optical-image protection scanner.

The scanner never mounts or executes the image.  It understands ISO9660/Joliet
volume descriptors on 2048-byte sectors and common 2352-byte raw sectors, walks
bounded directory records, and also performs a streaming raw signature scan.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

SCAN_CHUNK = 4 * 1024 * 1024
MAX_ISO_DEPTH = 16
MAX_ISO_ENTRIES = 100_000
MAX_DIRECTORY_EXTENT = 64 * 1024 * 1024
MAX_FILE_SAMPLE = 2 * 1024 * 1024

SIGNATURES: dict[str, tuple[bytes, ...]] = {
    "SafeDisc": (
        b"safedisc", b"secdrv.sys", b"clokspl.exe", b"00000001.tmp", b"boowoo",
    ),
    "SecuROM": (
        b"securom", b"cms16.dll", b"cms_95.dll", b"cms_nt.dll", b"sintf16.dll", b"sintf32.dll",
    ),
    "StarForce": (
        b"starforce", b"sfdrv", b"sfhlp", b"protection.dll",
    ),
    "LaserLock": (
        b"laserlock", b"laserlok", b"laserlok.in",
    ),
    "ProtectCD": (
        b"protectcd", b"vob protectcd", b"vobprotect",
    ),
    "Tages": (
        b"tages", b"tagesprotection", b"tagesclient",
    ),
    "CD-Cops": (
        b"cd-cops", b"cdcops", b"cdcops.dll",
    ),
    "CopyLok/CodeLok": (
        b"copylok", b"codelok", b"code lok",
    ),
    "DiscGuard": (
        b"discguard", b"disc guard",
    ),
}


@dataclass(frozen=True, slots=True)
class ScanFinding:
    protection: str
    confidence: str
    evidence: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScanResult:
    image: Path
    filesystem: str
    volume_id: str
    files_seen: int
    findings: tuple[ScanFinding, ...]
    notes: tuple[str, ...]


class ImageScannerError(RuntimeError):
    pass


class SectorReader:
    """Expose 2048-byte ISO user sectors from cooked or common raw layouts."""

    def __init__(self, path: Path):
        self.path = path.resolve(strict=True)
        self.size = self.path.stat().st_size
        self.sector_size, self.data_offset = self._detect_layout()

    def _probe(self, sector_size: int, offset: int) -> bool:
        pos = 16 * sector_size + offset
        if pos + 7 > self.size:
            return False
        with self.path.open("rb", buffering=0) as fh:
            fh.seek(pos)
            data = fh.read(7)
        return len(data) >= 6 and data[1:6] == b"CD001"

    def _detect_layout(self) -> tuple[int, int]:
        for sector_size, offset in ((2048, 0), (2352, 16), (2352, 24), (2336, 8)):
            if self._probe(sector_size, offset):
                return sector_size, offset
        raise ImageScannerError("Layout ISO9660 non riconosciuto (cooked/raw sector probe fallito).")

    def read_sector(self, lba: int) -> bytes:
        if lba < 0:
            raise ImageScannerError("LBA negativo.")
        pos = lba * self.sector_size + self.data_offset
        if pos + 2048 > self.size:
            raise ImageScannerError(f"LBA fuori immagine: {lba}")
        with self.path.open("rb", buffering=0) as fh:
            fh.seek(pos)
            data = fh.read(2048)
        if len(data) != 2048:
            raise ImageScannerError(f"Lettura settore incompleta a LBA {lba}")
        return data

    def read_extent(self, lba: int, length: int, *, limit: int | None = None) -> bytes:
        if length < 0:
            raise ImageScannerError("Lunghezza extent negativa.")
        if limit is not None:
            length = min(length, limit)
        chunks = []
        remaining = length
        sector = lba
        while remaining:
            data = self.read_sector(sector)
            take = min(remaining, 2048)
            chunks.append(data[:take])
            remaining -= take
            sector += 1
        return b"".join(chunks)


@dataclass(frozen=True, slots=True)
class _DirRecord:
    lba: int
    size: int
    is_dir: bool
    name: str


def _both32(data: bytes, offset: int) -> int:
    if offset + 4 > len(data):
        return 0
    return int.from_bytes(data[offset:offset + 4], "little", signed=False)


def _decode_iso_name(raw: bytes, joliet: bool) -> str:
    if raw in {b"\x00", b"\x01"}:
        return "." if raw == b"\x00" else ".."
    try:
        text = raw.decode("utf-16-be" if joliet else "ascii", errors="replace")
    except Exception:
        text = raw.decode("latin-1", errors="replace")
    return text.split(";", 1)[0].rstrip(".")


def _parse_dir_records(data: bytes, joliet: bool) -> Iterator[_DirRecord]:
    pos = 0
    while pos < len(data):
        length = data[pos]
        if length == 0:
            pos = ((pos // 2048) + 1) * 2048
            continue
        if length < 34 or pos + length > len(data):
            break
        rec = data[pos:pos + length]
        name_len = rec[32]
        if 33 + name_len > len(rec):
            break
        name = _decode_iso_name(rec[33:33 + name_len], joliet)
        yield _DirRecord(
            lba=_both32(rec, 2),
            size=_both32(rec, 10),
            is_dir=bool(rec[25] & 0x02),
            name=name,
        )
        pos += length


def _volume_descriptors(reader: SectorReader) -> tuple[bytes | None, bytes | None]:
    primary = supplementary = None
    for lba in range(16, 16 + 64):
        sector = reader.read_sector(lba)
        if sector[1:6] != b"CD001":
            continue
        kind = sector[0]
        if kind == 1 and primary is None:
            primary = sector
        elif kind == 2 and sector[88:91] in {b"%/@", b"%/C", b"%/E"}:
            supplementary = sector
        elif kind == 255:
            break
    return primary, supplementary


def _volume_id(vd: bytes, joliet: bool) -> str:
    raw = vd[40:72]
    if joliet:
        return raw.decode("utf-16-be", errors="replace").strip(" \x00")
    return raw.decode("ascii", errors="replace").strip(" \x00")


def _root_record(vd: bytes, joliet: bool) -> _DirRecord:
    rec = vd[156:190]
    records = list(_parse_dir_records(rec, joliet))
    if not records:
        raise ImageScannerError("Root directory record ISO9660 non valido.")
    return records[0]


def _walk_iso(reader: SectorReader, root: _DirRecord, joliet: bool) -> Iterator[tuple[str, _DirRecord]]:
    stack: list[tuple[str, _DirRecord, int]] = [("", root, 0)]
    visited_dirs: set[tuple[int, int]] = set()
    entries = 0
    while stack:
        prefix, directory, depth = stack.pop()
        if depth > MAX_ISO_DEPTH:
            continue
        if directory.size > MAX_DIRECTORY_EXTENT:
            raise ImageScannerError(
                f"Directory ISO troppo grande: {directory.size} byte (limite {MAX_DIRECTORY_EXTENT})."
            )
        key = (directory.lba, directory.size)
        if key in visited_dirs:
            continue
        visited_dirs.add(key)
        data = reader.read_extent(directory.lba, directory.size)
        for record in _parse_dir_records(data, joliet):
            if record.name in {".", "..", ""}:
                continue
            entries += 1
            if entries > MAX_ISO_ENTRIES:
                raise ImageScannerError("Troppi record ISO: limite di sicurezza superato.")
            path = f"{prefix}/{record.name}" if prefix else record.name
            yield path, record
            if record.is_dir:
                stack.append((path, record, depth + 1))


def _scan_signatures(chunks: Iterable[tuple[str, bytes]]) -> dict[str, set[str]]:
    evidence: dict[str, set[str]] = {name: set() for name in SIGNATURES}
    for label, data in chunks:
        lower = data.lower()
        for protection, patterns in SIGNATURES.items():
            for pattern in patterns:
                if pattern in lower:
                    evidence[protection].add(f"{label}: {pattern.decode('ascii', errors='replace')}")
    return evidence


def _merge_evidence(target: dict[str, set[str]], source: dict[str, set[str]]) -> None:
    for name, values in source.items():
        target.setdefault(name, set()).update(values)


def _stream_raw_signatures(path: Path) -> dict[str, set[str]]:
    max_pattern = max(len(p) for values in SIGNATURES.values() for p in values)
    overlap = b""
    evidence: dict[str, set[str]] = {name: set() for name in SIGNATURES}
    offset = 0
    with path.open("rb", buffering=0) as fh:
        while True:
            chunk = fh.read(SCAN_CHUNK)
            if not chunk:
                break
            data = overlap + chunk
            lower = data.lower()
            logical_start = max(0, offset - len(overlap))
            for protection, patterns in SIGNATURES.items():
                for pattern in patterns:
                    start = 0
                    while True:
                        idx = lower.find(pattern, start)
                        if idx < 0:
                            break
                        evidence[protection].add(
                            f"raw@0x{logical_start + idx:x}: {pattern.decode('ascii', errors='replace')}"
                        )
                        break
            overlap = data[-(max_pattern - 1):] if max_pattern > 1 else b""
            offset += len(chunk)
    return evidence


def scan_image(path: Path) -> ScanResult:
    path = path.expanduser().resolve(strict=True)
    if not path.is_file():
        raise ImageScannerError(f"Immagine non valida: {path}")
    evidence = _stream_raw_signatures(path)
    notes: list[str] = ["Scansione raw streaming completata; nessun mount/esecuzione effettuato."]
    filesystem = "raw/unknown"
    volume = ""
    files_seen = 0
    try:
        reader = SectorReader(path)
        primary, supplementary = _volume_descriptors(reader)
        selected = supplementary or primary
        if selected is None:
            raise ImageScannerError("Volume descriptor ISO9660 assente.")
        joliet = supplementary is not None
        filesystem = (
            f"ISO9660/Joliet ({reader.sector_size}-byte sectors, data+{reader.data_offset})"
            if joliet else f"ISO9660 ({reader.sector_size}-byte sectors, data+{reader.data_offset})"
        )
        volume = _volume_id(selected, joliet)
        root = _root_record(selected, joliet)
        name_chunks: list[tuple[str, bytes]] = []
        file_samples: list[tuple[str, bytes]] = []
        for iso_path, record in _walk_iso(reader, root, joliet):
            files_seen += 1
            encoded = iso_path.encode("utf-8", errors="replace")
            name_chunks.append((f"iso-name:{iso_path}", encoded))
            if not record.is_dir and record.size > 0:
                low = iso_path.casefold()
                interesting = low.endswith((".exe", ".dll", ".sys", ".vxd", ".inf", ".ini", ".tmp"))
                if interesting:
                    try:
                        sample = reader.read_extent(record.lba, record.size, limit=MAX_FILE_SAMPLE)
                    except ImageScannerError:
                        continue
                    file_samples.append((f"iso-file:{iso_path}", sample))
        _merge_evidence(evidence, _scan_signatures(name_chunks))
        _merge_evidence(evidence, _scan_signatures(file_samples))
        notes.append(f"Directory ISO letta direttamente: {files_seen} record file/directory.")
    except ImageScannerError as exc:
        notes.append(f"Parser ISO/Joliet non applicabile: {exc}")

    findings: list[ScanFinding] = []
    for protection, values in evidence.items():
        if not values:
            continue
        ordered = tuple(sorted(values)[:16])
        strong = any(not item.startswith("raw@") for item in ordered)
        confidence = "alta" if strong and len(ordered) >= 2 else "media" if strong else "bassa"
        findings.append(ScanFinding(protection, confidence, ordered))
    findings.sort(key=lambda item: item.protection.casefold())
    return ScanResult(path, filesystem, volume, files_seen, tuple(findings), tuple(notes))


def compare_catalog_protection(declared: str, scan: ScanResult) -> tuple[str, ...]:
    """Explicitly compare DAT protection metadata with scanner observations."""
    declared = (declared or "").strip()
    observed = {item.protection.casefold(): item for item in scan.findings}
    if not declared:
        if observed:
            return (
                "DAT senza metadata protezione; scanner osserva: "
                + ", ".join(item.protection for item in scan.findings),
            )
        return ("DAT e scanner non dichiarano/rilevano una protezione nota.",)
    tokens = {
        name.casefold()
        for name in SIGNATURES
        if name.casefold().replace("/", "") in declared.casefold().replace("/", "")
        or name.casefold().split("/")[0] in declared.casefold()
    }
    if not tokens:
        return (f"Protezione DAT non mappata dal dizionario scanner: {declared}",)
    matched = [item.protection for key, item in observed.items() if key in tokens]
    if matched:
        return (f"DAT↔scanner coerenti: {declared} ↔ {', '.join(matched)}",)
    return (f"DAT dichiara {declared}, ma lo scanner non ha trovato firme corrispondenti.",)


def format_scan(result: ScanResult) -> str:
    lines = [
        f"Scanner: {result.image.name}",
        f"Filesystem: {result.filesystem}",
        f"Volume ID: {result.volume_id or '—'}",
        f"Record ISO: {result.files_seen}",
    ]
    if result.findings:
        for finding in result.findings:
            lines.append(f"[{finding.confidence.upper()}] {finding.protection}")
            lines.extend(f"  - {e}" for e in finding.evidence)
    else:
        lines.append("Nessuna firma nota rilevata.")
    lines.extend(f"[INFO] {note}" for note in result.notes)
    return "\n".join(lines)
