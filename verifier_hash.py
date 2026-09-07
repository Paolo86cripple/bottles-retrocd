#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import hashlib
import sqlite3
import time
import zlib
from pathlib import Path

from verifier_common import (
    FileHash, HASH_CACHE_SCHEMA, HASH_CHUNK_SIZE, VerificationError,
    _ensure_private_dir, verifier_cache_dir,
)

class HashCache:
    def __init__(self, path: Path | None = None):
        self.path = path or (verifier_cache_dir() / "hash-cache.sqlite3")
        _ensure_private_dir(self.path.parent)
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30)
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def _ensure_schema(self) -> None:
        with contextlib.closing(self._connect()) as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, HASH_CACHE_SCHEMA):
                db.execute("DROP TABLE IF EXISTS file_hashes")
            db.execute(
                """
                CREATE TABLE IF NOT EXISTS file_hashes (
                    path TEXT PRIMARY KEY,
                    dev INTEGER NOT NULL,
                    inode INTEGER NOT NULL,
                    size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    ctime_ns INTEGER NOT NULL,
                    crc32 TEXT NOT NULL,
                    md5 TEXT NOT NULL,
                    sha1 TEXT NOT NULL,
                    hashed_at INTEGER NOT NULL
                )
                """
            )
            db.execute(f"PRAGMA user_version={HASH_CACHE_SCHEMA}")
            db.commit()

    @staticmethod
    def _identity(path: Path) -> tuple[int, int, int, int, int]:
        st = path.stat()
        return st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns

    def get(self, path: Path) -> FileHash | None:
        path = path.resolve(strict=True)
        dev, inode, size, mtime_ns, ctime_ns = self._identity(path)
        with contextlib.closing(self._connect()) as db:
            row = db.execute(
                "SELECT dev,inode,size,mtime_ns,ctime_ns,crc32,md5,sha1 "
                "FROM file_hashes WHERE path=?",
                (str(path),),
            ).fetchone()
        if row is None or tuple(row[:5]) != (dev, inode, size, mtime_ns, ctime_ns):
            return None
        return FileHash(path, size, row[5], row[6], row[7], cached=True)

    def put(self, result: FileHash) -> None:
        dev, inode, size, mtime_ns, ctime_ns = self._identity(result.path)
        # Refuse to cache a result if the file changed while/after hashing.
        if size != result.size:
            raise VerificationError(f"File cambiato durante hashing: {result.path}")
        with contextlib.closing(self._connect()) as db:
            db.execute(
                """
                INSERT INTO file_hashes(path,dev,inode,size,mtime_ns,ctime_ns,crc32,md5,sha1,hashed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(path) DO UPDATE SET
                    dev=excluded.dev, inode=excluded.inode, size=excluded.size,
                    mtime_ns=excluded.mtime_ns, ctime_ns=excluded.ctime_ns,
                    crc32=excluded.crc32, md5=excluded.md5, sha1=excluded.sha1,
                    hashed_at=excluded.hashed_at
                """,
                (
                    str(result.path), dev, inode, size, mtime_ns, ctime_ns,
                    result.crc32, result.md5, result.sha1, int(time.time()),
                ),
            )
            db.commit()

    def prune_missing(self) -> int:
        with contextlib.closing(self._connect()) as db:
            rows = db.execute("SELECT path FROM file_hashes").fetchall()
            missing = [path for (path,) in rows if not Path(path).exists()]
            db.executemany("DELETE FROM file_hashes WHERE path=?", ((p,) for p in missing))
            db.commit()
            return len(missing)


def hash_file(path: Path, cache: HashCache | None = None) -> FileHash:
    path = path.expanduser().resolve(strict=True)
    if not path.is_file():
        raise VerificationError(f"Non è un file: {path}")
    if cache is not None:
        hit = cache.get(path)
        if hit is not None:
            return hit

    before = path.stat()
    md5 = hashlib.md5(usedforsecurity=False)
    sha1 = hashlib.sha1(usedforsecurity=False)
    crc = 0
    total = 0
    with path.open("rb", buffering=0) as fh:
        while True:
            chunk = fh.read(HASH_CHUNK_SIZE)
            if not chunk:
                break
            total += len(chunk)
            crc = zlib.crc32(chunk, crc)
            md5.update(chunk)
            sha1.update(chunk)
    after = path.stat()
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if identity_before != identity_after or total != after.st_size:
        raise VerificationError(f"File modificato durante hashing: {path}")
    result = FileHash(
        path=path,
        size=total,
        crc32=f"{crc & 0xffffffff:08x}",
        md5=md5.hexdigest(),
        sha1=sha1.hexdigest(),
        cached=False,
    )
    if cache is not None:
        cache.put(result)
    return result
