from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from dgvoodoo_backend import BottleInfo, DgVoodooError, ReleaseInfo
from dgvoodoo_probe import (
    PROBE_CONFIG_NAME,
    PROBE_DDRAW_NAME,
    PROBE_DIR_NAME,
    PROBE_EXE_NAME,
    PROBE_UNRELATED_NAME,
    clean_probe,
    install_probe_from_archive,
    prepare_probe,
    probe_status,
    tamper_refusal_probe,
    uninstall_probe,
)


class DgVoodooProbeTests(unittest.TestCase):
    def _bottle(self, root: Path) -> BottleInfo:
        bottle_root = root / "bottle"
        drive = bottle_root / "drive_c"
        drive.mkdir(parents=True)
        (bottle_root / "bottle.yml").write_text("Name: Probe\n", encoding="utf-8")
        return BottleInfo("Probe", bottle_root.resolve(), drive.resolve())

    def _archive(self, path: Path) -> tuple[Path, ReleaseInfo]:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("dgVoodoo.conf", b"[General]\nOutputAPI = bestavailable\n")
            zf.writestr("dgVoodooCpl.exe", b"MZ-test-control-panel")
            zf.writestr("MS/x86/DDraw.dll", b"official-ddraw-x86-test-payload")
        payload = path.read_bytes()
        release = ReleaseInfo(
            tag="v2.87.4",
            version="2.87.4",
            asset_name="dgVoodoo2_87_4.zip",
            download_url="https://github.com/dege-diosg/dgVoodoo2/releases/download/v2.87.4/dgVoodoo2_87_4.zip",
            sha256=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )
        return path, release

    def test_prepare_probe_is_x86_and_baseline_clean(self):
        with tempfile.TemporaryDirectory() as td:
            bottle = self._bottle(Path(td))
            status = prepare_probe(bottle)
            self.assertTrue(status.baseline_ok)
            self.assertEqual(PROBE_EXE_NAME, status.executable.name)
            self.assertEqual(PROBE_DIR_NAME, status.root.name)
            self.assertTrue((status.root / PROBE_DDRAW_NAME).is_file())
            self.assertTrue((status.root / PROBE_CONFIG_NAME).is_file())
            self.assertTrue((status.root / PROBE_UNRELATED_NAME).is_file())
            with self.assertRaisesRegex(DgVoodooError, "già esistente"):
                prepare_probe(bottle)

    def test_transaction_preserves_config_unrelated_and_restores_ddraw(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle = self._bottle(root)
            status = prepare_probe(bottle)
            before_ddraw = (status.root / PROBE_DDRAW_NAME).read_bytes()
            before_config = (status.root / PROBE_CONFIG_NAME).read_bytes()
            before_unrelated = (status.root / PROBE_UNRELATED_NAME).read_bytes()
            archive, release = self._archive(root / "dg.zip")
            with patch.dict(os.environ, {"XDG_DATA_HOME": str(root / "xdg-data")}, clear=False):
                report = install_probe_from_archive(bottle, release, archive)
                self.assertEqual("2.87.4", report.version)
                self.assertNotEqual(before_ddraw, (status.root / PROBE_DDRAW_NAME).read_bytes())
                self.assertEqual(before_config, (status.root / PROBE_CONFIG_NAME).read_bytes())
                self.assertEqual(before_unrelated, (status.root / PROBE_UNRELATED_NAME).read_bytes())
                self.assertTrue((status.root / "dgVoodooCpl.exe").is_file())
                restored = uninstall_probe(bottle)
            self.assertTrue(restored.baseline_ok)
            self.assertEqual(before_ddraw, (status.root / PROBE_DDRAW_NAME).read_bytes())
            self.assertEqual(before_config, (status.root / PROBE_CONFIG_NAME).read_bytes())
            self.assertEqual(before_unrelated, (status.root / PROBE_UNRELATED_NAME).read_bytes())
            self.assertFalse((status.root / "dgVoodooCpl.exe").exists())

    def test_tamper_refusal_restores_managed_bytes_then_uninstall_succeeds(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle = self._bottle(root)
            status = prepare_probe(bottle)
            archive, release = self._archive(root / "dg.zip")
            with patch.dict(os.environ, {"XDG_DATA_HOME": str(root / "xdg-data")}, clear=False):
                install_probe_from_archive(bottle, release, archive)
                installed = (status.root / PROBE_DDRAW_NAME).read_bytes()
                message = tamper_refusal_probe(bottle)
                self.assertIn("modificato dopo", message)
                self.assertEqual(installed, (status.root / PROBE_DDRAW_NAME).read_bytes())
                restored = uninstall_probe(bottle)
            self.assertTrue(restored.baseline_ok)

    def test_clean_refuses_unexpected_files_and_only_removes_clean_probe(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle = self._bottle(root)
            status = prepare_probe(bottle)
            extra = status.root / "do-not-touch.txt"
            extra.write_text("sentinel\n", encoding="utf-8")
            with self.assertRaisesRegex(DgVoodooError, "elementi inattesi"):
                clean_probe(bottle)
            self.assertTrue(extra.is_file())
            extra.unlink()
            clean_probe(bottle)
            self.assertFalse(status.root.exists())

    def test_status_detects_baseline_change(self):
        with tempfile.TemporaryDirectory() as td:
            bottle = self._bottle(Path(td))
            status = prepare_probe(bottle)
            (status.root / PROBE_UNRELATED_NAME).write_bytes(b"changed")
            self.assertFalse(probe_status(bottle).baseline_ok)


if __name__ == "__main__":
    unittest.main()
