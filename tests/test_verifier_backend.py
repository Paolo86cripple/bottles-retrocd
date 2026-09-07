from __future__ import annotations

import os
import stat
import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from unittest import mock
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import verifier_updates as vu
from verifier_backend import (
    CatalogIndex,
    HashCache,
    UpdateError,
    VerificationError,
    _materialise_dat_payload,
    _safe_catalog_source,
    _safe_zip_members,
    _validate_update_url,
    descriptor_payloads,
    format_verification,
    hash_file,
    import_dat_directory,
    parse_cue_payloads,
    parse_toc_payloads,
    update_official_source,
)


def dat_xml(game: str = "Game", roms: list[tuple[str, bytes]] | None = None, *, serial: str = "", version: str = "", protection: str = "") -> bytes:
    import hashlib
    import zlib
    roms = roms or [("track.bin", b"payload")]
    rows = []
    for name, payload in roms:
        rows.append(
            f'<rom name="{name}" size="{len(payload)}" crc="{zlib.crc32(payload) & 0xffffffff:08x}" '
            f'md5="{hashlib.md5(payload, usedforsecurity=False).hexdigest()}" sha1="{hashlib.sha1(payload, usedforsecurity=False).hexdigest()}" />'
        )
    extras = ""
    if serial:
        extras += f"<serial>{serial}</serial>"
    if version:
        extras += f"<version>{version}</version>"
    if protection:
        extras += f"<protection>{protection}</protection>"
    return (
        '<?xml version="1.0"?><datafile><header><name>Test DAT</name><version>1</version></header>'
        f'<game name="{game}"><description>{game}</description>{extras}{"".join(rows)}</game></datafile>'
    ).encode()


def zip_payload(files: dict[str, bytes]) -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in files.items():
            zf.writestr(name, payload)
    return out.getvalue()


class VerifierBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.cache = HashCache(self.root / "cache.sqlite3")
        self.index = CatalogIndex(self.root / "catalog.sqlite3", cache=self.cache)

    def tearDown(self):
        self.tmp.cleanup()

    def _datdir(self, source: str = "redump", payload: bytes | None = None) -> Path:
        directory = self.root / f"dat-{source}-{len(list(self.root.glob('dat-*')))}"
        directory.mkdir()
        (directory / f"{source}.dat").write_bytes(payload or dat_xml())
        return directory

    # 1
    def test_safe_catalog_source_accepts(self):
        self.assertEqual(_safe_catalog_source("redump_pc"), "redump_pc")

    # 2
    def test_safe_catalog_source_rejects_traversal(self):
        with self.assertRaises(VerificationError):
            _safe_catalog_source("../redump")

    # 3
    def test_cue_quoted_payload(self):
        payload = self.root / "Track 01.bin"; payload.write_bytes(b"abc")
        cue = self.root / "disc.cue"; cue.write_text('FILE "Track 01.bin" BINARY\n', encoding="ascii")
        self.assertEqual(parse_cue_payloads(cue, self.root), (payload.resolve(),))

    # 4
    def test_cue_latin1_filename(self):
        payload = self.root / "träck.bin"; payload.write_bytes(b"abc")
        cue = self.root / "disc.cue"; cue.write_bytes('FILE "träck.bin" BINARY\n'.encode("latin-1"))
        self.assertEqual(parse_cue_payloads(cue, self.root), (payload.resolve(),))

    # 5
    def test_cue_escape_rejected(self):
        outside = self.root.parent / "outside-verifier.bin"; outside.write_bytes(b"x")
        try:
            cue = self.root / "disc.cue"; cue.write_text(f'FILE "../{outside.name}" BINARY\n', encoding="ascii")
            with self.assertRaises(VerificationError):
                parse_cue_payloads(cue, self.root)
        finally:
            outside.unlink(missing_ok=True)

    # 6
    def test_cue_windows_absolute_rejected(self):
        cue = self.root / "disc.cue"; cue.write_text('FILE "C:\\dump\\track.bin" BINARY\n', encoding="ascii")
        with self.assertRaises(VerificationError):
            parse_cue_payloads(cue, self.root)

    # 7
    def test_cue_missing_payload_rejected(self):
        cue = self.root / "disc.cue"; cue.write_text('FILE "missing.bin" BINARY\n', encoding="ascii")
        with self.assertRaises(VerificationError):
            parse_cue_payloads(cue, self.root)

    # 8
    def test_toc_payload(self):
        payload = self.root / "track.bin"; payload.write_bytes(b"abc")
        toc = self.root / "disc.toc"; toc.write_text('DATAFILE "track.bin"\n', encoding="ascii")
        self.assertEqual(parse_toc_payloads(toc, self.root), (payload.resolve(),))

    # 9
    def test_ccd_companion_img(self):
        ccd = self.root / "disc.ccd"; ccd.write_text("[CloneCD]\n", encoding="ascii")
        img = self.root / "disc.img"; img.write_bytes(b"abc")
        self.assertEqual(descriptor_payloads(ccd, self.root), (img.resolve(),))

    # 10
    def test_mds_missing_companion_rejected(self):
        mds = self.root / "disc.mds"; mds.write_bytes(b"x")
        with self.assertRaises(VerificationError):
            descriptor_payloads(mds, self.root)

    # 11
    def test_hash_known_values(self):
        import hashlib, zlib
        p = self.root / "a.bin"; p.write_bytes(b"hello")
        got = hash_file(p)
        self.assertEqual(got.crc32, f"{zlib.crc32(b'hello') & 0xffffffff:08x}")
        self.assertEqual(got.md5, hashlib.md5(b"hello", usedforsecurity=False).hexdigest())
        self.assertEqual(got.sha1, hashlib.sha1(b"hello", usedforsecurity=False).hexdigest())

    # 12
    def test_hash_cache_hit(self):
        p = self.root / "a.bin"; p.write_bytes(b"hello")
        self.assertFalse(hash_file(p, self.cache).cached)
        self.assertTrue(hash_file(p, self.cache).cached)

    # 13
    def test_hash_cache_invalidates_on_change(self):
        p = self.root / "a.bin"; p.write_bytes(b"hello")
        first = hash_file(p, self.cache)
        p.write_bytes(b"HELLO!")
        second = hash_file(p, self.cache)
        self.assertFalse(second.cached)
        self.assertNotEqual(first.sha1, second.sha1)

    # 14
    def test_hash_cache_prune_missing(self):
        p = self.root / "a.bin"; p.write_bytes(b"hello")
        hash_file(p, self.cache); p.unlink()
        self.assertEqual(self.cache.prune_missing(), 1)

    # 15
    def test_catalog_rebuild_stats(self):
        directory = self._datdir()
        self.index.rebuild({"redump": directory})
        self.assertEqual(self.index.stats(), {"catalogs": 1, "games": 1, "roms": 1})
        self.assertEqual(stat.S_IMODE(self.index.path.stat().st_mode), 0o600)

    # 16
    def test_verify_match_one_to_one(self):
        payload = b"payload"; p = self.root / "track.bin"; p.write_bytes(payload)
        self.index.rebuild({"redump": self._datdir(payload=dat_xml("Game", [(p.name, payload)]))})
        result = self.index.verify(p, self.root)
        self.assertTrue(result.matched)
        self.assertEqual(len(result.exact_matches), 1)

    # 17
    def test_verify_mismatch(self):
        p = self.root / "track.bin"; p.write_bytes(b"different")
        self.index.rebuild({"redump": self._datdir(payload=dat_xml())})
        self.assertEqual(self.index.verify(p, self.root).status, "MISMATCH")

    # 18
    def test_verify_ambiguous_duplicate_catalog_records(self):
        p = self.root / "track.bin"; p.write_bytes(b"payload")
        a = self._datdir("redump", dat_xml("A")); b = self._datdir("tosec", dat_xml("B"))
        self.index.rebuild({"redump": a, "tosec": b})
        self.assertEqual(self.index.verify(p, self.root).status, "AMBIGUOUS")

    # 19
    def test_verify_multifile_cue_exact(self):
        one = self.root / "one.bin"; two = self.root / "two.bin"
        one.write_bytes(b"one"); two.write_bytes(b"two")
        cue = self.root / "disc.cue"; cue.write_text('FILE "one.bin" BINARY\nFILE "two.bin" BINARY\n', encoding="ascii")
        self.index.rebuild({"redump": self._datdir(payload=dat_xml("Multi", [("one.bin", b"one"), ("two.bin", b"two")]))})
        self.assertTrue(self.index.verify(cue, self.root).matched)

    def test_verify_cue_descriptor_when_dat_declares_it(self):
        payload = b"disc payload"
        bin_file = self.root / "disc.bin"; bin_file.write_bytes(payload)
        cue_bytes = b'FILE "disc.bin" BINARY\n'
        cue = self.root / "disc.cue"; cue.write_bytes(cue_bytes)
        self.index.rebuild({
            "redump": self._datdir(
                payload=dat_xml("CueSet", [(cue.name, cue_bytes), (bin_file.name, payload)])
            )
        })
        result = self.index.verify(cue, self.root)
        self.assertTrue(result.matched)
        self.assertEqual(len(result.payloads), 1)
        self.assertEqual(result.payloads[0].path, bin_file.resolve())

    def test_verify_declared_cue_descriptor_must_match(self):
        payload = b"disc payload"
        bin_file = self.root / "disc.bin"; bin_file.write_bytes(payload)
        expected_cue = b'FILE "disc.bin" BINARY\n'
        cue = self.root / "disc.cue"; cue.write_bytes(expected_cue + b"REM local-change\n")
        self.index.rebuild({
            "redump": self._datdir(
                payload=dat_xml("CueSet", [(cue.name, expected_cue), (bin_file.name, payload)])
            )
        })
        self.assertEqual(self.index.verify(cue, self.root).status, "MISMATCH")

    # 20
    def test_verify_partial_multifile_is_not_exact(self):
        one = self.root / "one.bin"; two = self.root / "two.bin"
        one.write_bytes(b"one"); two.write_bytes(b"changed")
        cue = self.root / "disc.cue"; cue.write_text('FILE "one.bin" BINARY\nFILE "two.bin" BINARY\n', encoding="ascii")
        self.index.rebuild({"redump": self._datdir(payload=dat_xml("Multi", [("one.bin", b"one"), ("two.bin", b"two")]))})
        self.assertEqual(self.index.verify(cue, self.root).status, "MISMATCH")

    # 21
    def test_verify_without_index(self):
        p = self.root / "x.bin"; p.write_bytes(b"x")
        empty = CatalogIndex(self.root / "missing.sqlite3", cache=self.cache)
        self.assertEqual(empty.verify(p, self.root).status, "NO_INDEX")

    # 22
    def test_verify_set(self):
        p1 = self.root / "d1.bin"; p2 = self.root / "d2.bin"
        p1.write_bytes(b"one"); p2.write_bytes(b"two")
        datdir = self.root / "setdat"; datdir.mkdir()
        (datdir / "a.dat").write_bytes(dat_xml("D1", [(p1.name, b"one")]))
        (datdir / "b.dat").write_bytes(dat_xml("D2", [(p2.name, b"two")]))
        self.index.rebuild({"redump": datdir})
        self.assertEqual(self.index.verify_set([p1, p2], self.root).status, "MATCH")

    # 23
    def test_update_url_accepts_official_https(self):
        self.assertEqual(_validate_update_url("https://redump.org/datfile/pc/"), "https://redump.org/datfile/pc/")

    # 24
    def test_update_url_rejects_http(self):
        with self.assertRaises(UpdateError):
            _validate_update_url("http://redump.org/datfile/pc/")

    # 25
    def test_update_url_rejects_foreign_host(self):
        with self.assertRaises(UpdateError):
            _validate_update_url("https://example.com/redump.dat")

    # 26
    def test_zip_traversal_rejected(self):
        payload = zip_payload({"../escape.dat": dat_xml()})
        with zipfile.ZipFile(BytesIO(payload)) as zf:
            with self.assertRaises(UpdateError):
                _safe_zip_members(zf)

    # 27
    def test_zip_symlink_rejected(self):
        out = BytesIO()
        with zipfile.ZipFile(out, "w") as zf:
            info = zipfile.ZipInfo("link.dat")
            info.create_system = 3
            info.external_attr = (0o120777 << 16)
            zf.writestr(info, b"target")
        with zipfile.ZipFile(BytesIO(out.getvalue())) as zf:
            with self.assertRaises(UpdateError):
                _safe_zip_members(zf)

    # 28
    def test_materialise_raw_logiqx(self):
        dest = self.root / "rawdest"
        self.assertEqual(_materialise_dat_payload(dat_xml(), dest, "redump"), 1)
        self.assertTrue((dest / "redump.dat").is_file())

    # 29
    def test_materialise_zip_flattens_dat(self):
        dest = self.root / "zipdest"
        payload = zip_payload({"nested/a.dat": dat_xml("A"), "other/b.xml": dat_xml("B")})
        self.assertEqual(_materialise_dat_payload(payload, dest, "tosec"), 2)
        self.assertEqual(sorted(p.name for p in dest.iterdir()), ["a.dat", "b.xml"])

    # 30
    def test_import_local_does_not_modify_originals(self):
        src = self._datdir("manual")
        file = next(src.iterdir()); before = (file.read_bytes(), file.stat().st_mtime_ns)
        data_root = self.root / "data"
        index = CatalogIndex(data_root / "catalog.sqlite3", cache=self.cache)
        report = import_dat_directory("manual", src, data_root=data_root, catalog=index)
        self.assertGreater(report.roms, 0)
        self.assertEqual(before, (file.read_bytes(), file.stat().st_mtime_ns))

    # 31
    def test_import_invalid_dat_preserves_previous_generation(self):
        data_root = self.root / "data"; index = CatalogIndex(data_root / "catalog.sqlite3", cache=self.cache)
        good = self._datdir("manual", dat_xml("Good"))
        import_dat_directory("manual", good, data_root=data_root, catalog=index)
        db_before = index.path.read_bytes(); dat_before = next((data_root / "manual").iterdir()).read_bytes()
        bad = self._datdir("bad"); next(bad.iterdir()).write_text("<datafile><broken>", encoding="ascii")
        with self.assertRaises(VerificationError):
            import_dat_directory("manual", bad, data_root=data_root, catalog=index)
        self.assertEqual(index.path.read_bytes(), db_before)
        self.assertEqual(next((data_root / "manual").iterdir()).read_bytes(), dat_before)

    # 32
    def test_official_update_synthetic_redump(self):
        data_root = self.root / "data"; index = CatalogIndex(data_root / "catalog.sqlite3", cache=self.cache)
        def download(url): return dat_xml("Official"), "https://redump.org/datfile/pc/"
        report = update_official_source("redump", data_root=data_root, catalog=index, downloader=download)
        self.assertEqual(report.source, "redump")
        self.assertGreater(report.roms, 0)
        self.assertTrue((data_root / "redump" / "redump.dat").is_file())

    # 33
    def test_official_invalid_xml_preserves_previous_generation(self):
        data_root = self.root / "data"; index = CatalogIndex(data_root / "catalog.sqlite3", cache=self.cache)
        good = lambda url: (dat_xml("Good"), "https://redump.org/datfile/pc/")
        update_official_source("redump", data_root=data_root, catalog=index, downloader=good)
        db_before = index.path.read_bytes(); dat_before = (data_root / "redump" / "redump.dat").read_bytes()
        bad = lambda url: (b"<datafile><broken>", "https://redump.org/datfile/pc/")
        with self.assertRaises(VerificationError):
            update_official_source("redump", data_root=data_root, catalog=index, downloader=bad)
        self.assertEqual(index.path.read_bytes(), db_before)
        self.assertEqual((data_root / "redump" / "redump.dat").read_bytes(), dat_before)

    # 34
    def test_replace_failure_restores_previous_generation(self):
        data_root = self.root / "data"; index = CatalogIndex(data_root / "catalog.sqlite3", cache=self.cache)
        old = lambda url: (dat_xml("Old"), "https://redump.org/datfile/pc/")
        new = lambda url: (dat_xml("New", [("new.bin", b"new")]), "https://redump.org/datfile/pc/")
        update_official_source("redump", data_root=data_root, catalog=index, downloader=old)
        db_before = index.path.read_bytes(); dat_before = (data_root / "redump" / "redump.dat").read_bytes()
        real_replace = vu.os.replace
        failed = {"done": False}
        def flaky(src, dst):
            src_p, dst_p = Path(src), Path(dst)
            if not failed["done"] and dst_p == index.path and src_p.name == "catalog.sqlite3" and ".redump-update-" in str(src_p.parent):
                failed["done"] = True
                raise OSError("injected replace failure")
            return real_replace(src, dst)
        with mock.patch.object(vu.os, "replace", side_effect=flaky):
            with self.assertRaises(OSError):
                update_official_source("redump", data_root=data_root, catalog=index, downloader=new)
        self.assertTrue(failed["done"])
        self.assertEqual(index.path.read_bytes(), db_before)
        self.assertEqual((data_root / "redump" / "redump.dat").read_bytes(), dat_before)

    # 35
    def test_format_verification_includes_metadata(self):
        p = self.root / "track.bin"; p.write_bytes(b"payload")
        self.index.rebuild({"redump": self._datdir(payload=dat_xml("Meta", [(p.name, b"payload")], serial="ABC-123", version="1.2", protection="SafeDisc"))})
        text = format_verification(self.index.verify(p, self.root))
        self.assertIn("MATCH 1:1", text)
        self.assertIn("serial=ABC-123", text)
        self.assertIn("version=1.2", text)
        self.assertIn("protection=SafeDisc", text)


if __name__ == "__main__":
    unittest.main()
