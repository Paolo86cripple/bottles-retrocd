from __future__ import annotations

import contextlib
import hashlib
import tempfile
import unittest
import zlib
from pathlib import Path

import verifier_updates as vu
from verifier_catalog import CatalogIndex
from verifier_hash import HashCache


def dat_xml(*, serial: str = "SERIAL-123", version: str = "v1.0") -> bytes:
    payload = b"payload"
    return (
        '<?xml version="1.0"?><datafile><header><name>Redump PC</name><version>1</version></header>'
        '<game name="Game"><description>Game</description>'
        f'<serial>{serial}</serial><version>{version}</version>'
        f'<rom name="track.bin" size="{len(payload)}" '
        f'crc="{zlib.crc32(payload) & 0xffffffff:08x}" '
        f'md5="{hashlib.md5(payload, usedforsecurity=False).hexdigest()}" '
        f'sha1="{hashlib.sha1(payload, usedforsecurity=False).hexdigest()}" />'
        '</game></datafile>'
    ).encode()


class RedumpInfoUpdaterTests(unittest.TestCase):
    def test_current_redump_https_host_is_allowed(self):
        self.assertEqual(vu._validate_update_url(vu.REDUMP_PC_URL), vu.REDUMP_PC_URL)
        self.assertEqual(
            vu._validate_update_url(vu.REDUMP_PC_FALLBACK_URL),
            vu.REDUMP_PC_FALLBACK_URL,
        )
        with self.assertRaises(vu.UpdateError):
            vu._validate_update_url("http://redump.info/datfile/pc/")

    def test_redump_prefers_serial_version_endpoint(self):
        calls: list[str] = []

        def downloader(url: str):
            calls.append(url)
            return dat_xml(), url

        payload, final_url = vu._download_redump_pc(downloader)
        self.assertIn(b"<serial>SERIAL-123</serial>", payload)
        self.assertEqual(final_url, vu.REDUMP_PC_URL)
        self.assertEqual(calls, [vu.REDUMP_PC_URL])

    def test_redump_falls_back_only_to_official_standard_dat(self):
        calls: list[str] = []

        def downloader(url: str):
            calls.append(url)
            if url == vu.REDUMP_PC_URL:
                return b"<html>temporary error</html>", url
            return dat_xml(serial="", version=""), url

        payload, final_url = vu._download_redump_pc(downloader)
        self.assertIn(b"<datafile", payload)
        self.assertEqual(final_url, vu.REDUMP_PC_FALLBACK_URL)
        self.assertEqual(calls, [vu.REDUMP_PC_URL, vu.REDUMP_PC_FALLBACK_URL])

    def test_official_update_indexes_serial_and_version_from_redump_info(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            data_root = root / "data"
            cache = HashCache(root / "cache.sqlite3")
            catalog = CatalogIndex(data_root / "catalog.sqlite3", cache=cache)

            def downloader(url: str):
                return dat_xml(), vu.REDUMP_PC_URL

            report = vu.update_official_source(
                "redump",
                data_root=data_root,
                catalog=catalog,
                downloader=downloader,
            )
            self.assertEqual(report.url, vu.REDUMP_PC_URL)
            with contextlib.closing(catalog._connect()) as db:
                row = db.execute("SELECT serial, version FROM games").fetchone()
            self.assertEqual(row, ("SERIAL-123", "v1.0"))


if __name__ == "__main__":
    unittest.main()
