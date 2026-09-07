#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import hashlib
import os
import re
import sqlite3
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Iterable, Sequence

from verifier_common import (
    CATALOG_SCHEMA, HASH_CHUNK_SIZE, CatalogMatch, FileMatch, SetVerificationResult, VerificationError,
    VerificationResult, _child_text, _ensure_private_dir, _normalise_hex,
    _normalise_size, _safe_catalog_source, _strip_ns, descriptor_payloads,
    verifier_data_dir,
)
from verifier_hash import HashCache, hash_file

class CatalogIndex:
    def __init__(self, path: Path | None = None, cache: HashCache | None = None):
        self.path = path or (verifier_data_dir() / "catalog.sqlite3")
        self.cache = cache or HashCache()

    def exists(self) -> bool:
        return self.path.is_file()

    def _connect(self, path: Path | None = None) -> sqlite3.Connection:
        db_path = path or self.path
        conn = sqlite3.connect(db_path, timeout=30)
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    @staticmethod
    def _create_schema(db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE catalogs(
                id INTEGER PRIMARY KEY,
                source TEXT NOT NULL,
                dat_name TEXT NOT NULL,
                header_name TEXT NOT NULL,
                version TEXT NOT NULL,
                description TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                record_count INTEGER NOT NULL DEFAULT 0,
                UNIQUE(source, dat_name)
            );
            CREATE TABLE games(
                id INTEGER PRIMARY KEY,
                catalog_id INTEGER NOT NULL REFERENCES catalogs(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                serial TEXT NOT NULL,
                version TEXT NOT NULL,
                protection TEXT NOT NULL
            );
            CREATE TABLE roms(
                id INTEGER PRIMARY KEY,
                game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                size INTEGER,
                crc32 TEXT NOT NULL,
                md5 TEXT NOT NULL,
                sha1 TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE INDEX rom_sha1_size ON roms(sha1, size) WHERE sha1 <> '';
            CREATE INDEX rom_md5_size ON roms(md5, size) WHERE md5 <> '';
            CREATE INDEX rom_crc_size ON roms(crc32, size) WHERE crc32 <> '';
            CREATE INDEX rom_game ON roms(game_id);
            CREATE INDEX games_catalog ON games(catalog_id);
            """
        )
        db.execute(f"PRAGMA user_version={CATALOG_SCHEMA}")
        db.execute("INSERT INTO meta(key,value) VALUES('built_at',?)", (str(int(time.time())),))

    @staticmethod
    def _parse_dat_into(db: sqlite3.Connection, dat_path: Path, source: str) -> tuple[int, int]:
        source = _safe_catalog_source(source)
        sha256 = hashlib.sha256()
        with dat_path.open("rb") as fh:
            for block in iter(lambda: fh.read(HASH_CHUNK_SIZE), b""):
                sha256.update(block)

        header_name = ""
        version = ""
        description = ""
        catalog_id: int | None = None
        games = 0
        roms = 0

        try:
            iterator = ET.iterparse(dat_path, events=("start", "end"))
            for event, elem in iterator:
                tag = _strip_ns(elem.tag)
                if event == "end" and tag == "header":
                    header_name = _child_text(elem, "name")
                    version = _child_text(elem, "version", "date")
                    description = _child_text(elem, "description")
                    elem.clear()
                    continue
                if event != "end" or tag not in {"game", "machine"}:
                    continue
                if catalog_id is None:
                    cur = db.execute(
                        "INSERT INTO catalogs(source,dat_name,header_name,version,description,sha256) "
                        "VALUES(?,?,?,?,?,?)",
                        (source, dat_path.name, header_name, version, description, sha256.hexdigest()),
                    )
                    catalog_id = int(cur.lastrowid)

                game_name = (elem.get("name") or _child_text(elem, "name") or "").strip()
                game_desc = _child_text(elem, "description") or game_name
                serial = _child_text(elem, "serial")
                game_version = _child_text(elem, "version")
                protection = _child_text(elem, "protection")
                # Some DATs carry useful freeform metadata in comment fields.
                if not protection:
                    comment = _child_text(elem, "comment")
                    if re.search(r"(?i)\b(?:safedisc|securom|starforce|laserlock|protectcd|tages|cd[- ]?cops|copylock|codelok)\b", comment):
                        protection = comment
                cur = db.execute(
                    "INSERT INTO games(catalog_id,name,description,serial,version,protection) "
                    "VALUES(?,?,?,?,?,?)",
                    (catalog_id, game_name, game_desc, serial, game_version, protection),
                )
                game_id = int(cur.lastrowid)
                games += 1

                for child in elem.iter():
                    if _strip_ns(child.tag) != "rom":
                        continue
                    size = _normalise_size(child.get("size"))
                    crc32 = _normalise_hex(child.get("crc") or child.get("crc32"), 8)
                    md5 = _normalise_hex(child.get("md5"), 32)
                    sha1 = _normalise_hex(child.get("sha1"), 40)
                    # A ROM without size or any usable hash is not verification material.
                    if size is None or not (sha1 or md5 or crc32):
                        continue
                    db.execute(
                        "INSERT INTO roms(game_id,name,size,crc32,md5,sha1,status) VALUES(?,?,?,?,?,?,?)",
                        (
                            game_id,
                            (child.get("name") or "").strip(),
                            size,
                            crc32,
                            md5,
                            sha1,
                            (child.get("status") or "").strip(),
                        ),
                    )
                    roms += 1
                elem.clear()
        except ET.ParseError as exc:
            raise VerificationError(f"DAT XML non valido {dat_path}: {exc}") from exc

        # Empty-but-valid Logiqx DAT: keep a catalog row so validation is explicit.
        if catalog_id is None:
            cur = db.execute(
                "INSERT INTO catalogs(source,dat_name,header_name,version,description,sha256) "
                "VALUES(?,?,?,?,?,?)",
                (source, dat_path.name, header_name, version, description, sha256.hexdigest()),
            )
            catalog_id = int(cur.lastrowid)
        db.execute("UPDATE catalogs SET record_count=? WHERE id=?", (roms, catalog_id))
        return games, roms

    def rebuild(self, source_dirs: dict[str, Path]) -> tuple[int, int, int]:
        _ensure_private_dir(self.path.parent)
        tmp = self.path.with_name(self.path.name + f".tmp-{os.getpid()}-{time.time_ns()}")
        total_catalogs = total_games = total_roms = 0
        try:
            with contextlib.closing(self._connect(tmp)) as db:
                self._create_schema(db)
                for source, directory in sorted(source_dirs.items()):
                    source = _safe_catalog_source(source)
                    if not directory.exists():
                        continue
                    paths = sorted(
                        (p for p in directory.rglob("*") if p.is_file() and p.suffix.lower() in {".dat", ".xml"}),
                        key=lambda p: str(p).casefold(),
                    )
                    for dat_path in paths:
                        games, roms = self._parse_dat_into(db, dat_path, source)
                        total_catalogs += 1
                        total_games += games
                        total_roms += roms
                db.execute("INSERT INTO meta(key,value) VALUES('catalog_count',?)", (str(total_catalogs),))
                db.execute("INSERT INTO meta(key,value) VALUES('game_count',?)", (str(total_games),))
                db.execute("INSERT INTO meta(key,value) VALUES('rom_count',?)", (str(total_roms),))
                db.commit()
                check = db.execute("PRAGMA integrity_check").fetchone()[0]
                if check != "ok":
                    raise VerificationError(f"SQLite integrity_check fallito: {check}")
                if total_roms <= 0:
                    raise VerificationError("Nessun record ROM valido nei DAT: indice non sostituito.")
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
            return total_catalogs, total_games, total_roms
        finally:
            with contextlib.suppress(FileNotFoundError):
                tmp.unlink()

    def stats(self) -> dict[str, int]:
        if not self.exists():
            return {"catalogs": 0, "games": 0, "roms": 0}
        with contextlib.closing(self._connect()) as db:
            return {
                "catalogs": int(db.execute("SELECT count(*) FROM catalogs").fetchone()[0]),
                "games": int(db.execute("SELECT count(*) FROM games").fetchone()[0]),
                "roms": int(db.execute("SELECT count(*) FROM roms").fetchone()[0]),
            }

    @staticmethod
    def _catalog_match(row: Sequence[object]) -> CatalogMatch:
        return CatalogMatch(
            source=str(row[0]), catalog=str(row[1]), game_name=str(row[2]),
            description=str(row[3]), serial=str(row[4]), version=str(row[5]),
            protection=str(row[6]), game_id=int(row[7]),
        )

    def _matching_games_for_file(self, db: sqlite3.Connection, item: FileHash) -> tuple[CatalogMatch, ...]:
        query_base = (
            "SELECT DISTINCT c.source,c.dat_name,g.name,g.description,g.serial,g.version,g.protection,g.id "
            "FROM roms r JOIN games g ON g.id=r.game_id JOIN catalogs c ON c.id=g.catalog_id "
            "WHERE r.size=? AND "
        )
        attempts = (("r.sha1=?", item.sha1), ("r.md5=?", item.md5), ("r.crc32=?", item.crc32))
        rows: list[Sequence[object]] = []
        for clause, value in attempts:
            if not value:
                continue
            rows = db.execute(query_base + clause, (item.size, value)).fetchall()
            if rows:
                break
        return tuple(self._catalog_match(row) for row in rows)

    @staticmethod
    def _rom_signature(row: Sequence[object]) -> tuple[int, str, str, str]:
        return int(row[0]), str(row[1]), str(row[2]), str(row[3])

    @classmethod
    def _rows_match_local(cls, rows: Sequence[Sequence[object]], local: Sequence[FileHash]) -> bool:
        if len(rows) != len(local):
            return False
        # Match a multiset. Prefer SHA-1, but keep all digests in the tuple so a
        # malformed DAT cannot accidentally weaken an exact-set comparison.
        expected = Counter(cls._rom_signature(row) for row in rows)
        actual = Counter((f.size, f.crc32, f.md5, f.sha1) for f in local)
        # DATs can omit MD5/SHA1; compare each expected record against one local record.
        if expected == actual:
            return True
        remaining = list(local)
        for size, crc32, md5, sha1 in expected.elements():
            found = None
            for idx, item in enumerate(remaining):
                if item.size != size:
                    continue
                if sha1 and item.sha1 != sha1:
                    continue
                if md5 and item.md5 != md5:
                    continue
                if crc32 and item.crc32 != crc32:
                    continue
                found = idx
                break
            if found is None:
                return False
            remaining.pop(found)
        return not remaining

    def _game_exact(
        self,
        db: sqlite3.Connection,
        game_id: int,
        payloads: Sequence[FileHash],
        descriptor_hash: FileHash | None = None,
    ) -> bool:
        rows = db.execute(
            "SELECT size,crc32,md5,sha1 FROM roms WHERE game_id=? ORDER BY id", (game_id,)
        ).fetchall()
        # Descriptor formats are metadata containers locally, but Redump may
        # explicitly catalogue the descriptor itself (for example a .cue) as
        # part of the verified disc set. First preserve payload-only DAT
        # semantics; only add the descriptor when the DAT requires one extra
        # exact file. This prevents an unlisted local descriptor from weakening
        # or invalidating an otherwise exact payload set.
        if self._rows_match_local(rows, payloads):
            return True
        if descriptor_hash is None:
            return False
        if any(item.path == descriptor_hash.path for item in payloads):
            return False
        return self._rows_match_local(rows, (*payloads, descriptor_hash))

    def verify(self, descriptor: Path, root: Path | None = None) -> VerificationResult:
        if not self.exists():
            return VerificationResult(
                descriptor=descriptor, payloads=(), status="NO_INDEX", exact_matches=(), file_matches=(),
                detail="Indice Redump/TOSEC assente: aggiorna o importa i DAT prima della verifica.",
            )
        payload_paths = descriptor_payloads(descriptor, root)
        hashes = tuple(hash_file(path, self.cache) for path in payload_paths)
        descriptor_path = descriptor.expanduser().resolve(strict=True)
        descriptor_hash = None
        if descriptor_path not in payload_paths:
            descriptor_hash = hash_file(descriptor_path, self.cache)
        with contextlib.closing(self._connect()) as db:
            file_matches = tuple(
                FileMatch(item, self._matching_games_for_file(db, item)) for item in hashes
            )
            if not file_matches:
                return VerificationResult(descriptor, hashes, "MISMATCH", (), (), "Nessun payload.")
            candidate_sets = [set(match.game_id for match in item.candidates) for item in file_matches]
            common = set.intersection(*candidate_sets) if candidate_sets else set()
            exact: list[CatalogMatch] = []
            by_id: dict[int, CatalogMatch] = {
                match.game_id: match
                for fm in file_matches
                for match in fm.candidates
            }
            for game_id in sorted(common):
                if self._game_exact(db, game_id, hashes, descriptor_hash):
                    exact.append(by_id[game_id])

        if len(exact) == 1:
            status = "MATCH"
            detail = "MATCH 1:1: tutti i file dichiarati dal set DAT corrispondono esattamente."
        elif len(exact) > 1:
            status = "AMBIGUOUS"
            detail = f"Match completo ma ambiguo: {len(exact)} record DAT equivalenti."
        else:
            status = "MISMATCH"
            matched_files = sum(bool(fm.candidates) for fm in file_matches)
            detail = f"Nessun set DAT 1:1 completo ({matched_files}/{len(file_matches)} payload con match individuale)."
        return VerificationResult(descriptor, hashes, status, tuple(exact), file_matches, detail)

    def verify_set(self, descriptors: Iterable[Path], root: Path | None = None) -> SetVerificationResult:
        return SetVerificationResult(tuple(self.verify(path, root) for path in descriptors))

