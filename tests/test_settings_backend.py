from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from settings_backend import load_settings, migrate_legacy_archive_root, save_settings


class SettingsBackendTests(unittest.TestCase):
    def test_gpu_display_and_archive_roundtrip_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(
            os.environ,
            {"XDG_CONFIG_HOME": td, "BOTTLES_RETRO_CD_ARCHIVE_ROOT": "", "BOTTLES_RETRO_CD_DATA_ROOT": ""},
            clear=False,
        ):
            archive = Path(td) / "archive"
            archive.mkdir()
            path = save_settings({
                "gpu_pci": "0000:03:00.0",
                "display_backend": "xwayland",
                "archive_root": str(archive),
            })
            loaded = load_settings()
            self.assertEqual(Path(td) / "bottles-retro-cd" / "config.toml", path)
            self.assertEqual("0000:03:00.0", loaded["gpu_pci"])
            self.assertEqual("xwayland", loaded["display_backend"])
            self.assertEqual(str(archive.resolve()), loaded["archive_root"])
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE(path.parent.stat().st_mode))

    def test_invalid_config_falls_back_safely(self):
        for legacy_exists in (False, True):
            with self.subTest(legacy_exists=legacy_exists), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                data_root = root / "Data"
                archive = data_root / "Downloads" / "retropc"
                if legacy_exists:
                    archive.mkdir(parents=True)
                with mock.patch.dict(
                    os.environ,
                    {
                        "XDG_CONFIG_HOME": str(root / "config"),
                        "BOTTLES_RETRO_CD_ARCHIVE_ROOT": "",
                        "BOTTLES_RETRO_CD_DATA_ROOT": str(data_root),
                    },
                    clear=False,
                ):
                    path = root / "config" / "bottles-retro-cd" / "config.toml"
                    path.parent.mkdir(parents=True)
                    path.write_text("not valid = [", encoding="utf-8")
                    before = path.read_bytes()
                    loaded = load_settings()
                    self.assertEqual("", loaded["gpu_pci"])
                    self.assertEqual("auto", loaded["display_backend"])
                    expected = str(archive.resolve()) if legacy_exists else ""
                    self.assertEqual(expected, loaded["archive_root"])
                    self.assertEqual(expected, migrate_legacy_archive_root())
                    self.assertEqual(before, path.read_bytes())

    def test_unknown_display_backend_is_normalized_to_auto(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(
            os.environ,
            {"XDG_CONFIG_HOME": td, "BOTTLES_RETRO_CD_ARCHIVE_ROOT": "", "BOTTLES_RETRO_CD_DATA_ROOT": ""},
            clear=False,
        ):
            path = Path(td) / "bottles-retro-cd" / "config.toml"
            path.parent.mkdir(parents=True)
            path.write_text(
                'schema_version = 1\ngpu_pci = ""\ndisplay_backend = "future-backend"\n',
                encoding="utf-8",
            )
            self.assertEqual("auto", load_settings()["display_backend"])

    def test_legacy_data_root_is_migrated_without_moving_archive(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            config_home = root / "config"
            data_root = root / "Data"
            archive = data_root / "Downloads" / "retropc"
            archive.mkdir(parents=True)
            config = config_home / "bottles-retro-cd" / "config.toml"
            config.parent.mkdir(parents=True)
            config.write_text(
                'schema_version = 1\ngpu_pci = "0000:03:00.0"\ndisplay_backend = "auto"\n',
                encoding="utf-8",
            )
            before = archive.stat()
            with mock.patch.dict(
                os.environ,
                {
                    "XDG_CONFIG_HOME": str(config_home),
                    "BOTTLES_RETRO_CD_ARCHIVE_ROOT": "",
                    "BOTTLES_RETRO_CD_DATA_ROOT": str(data_root),
                },
                clear=False,
            ):
                migrated = migrate_legacy_archive_root()
                loaded = load_settings()
            after = archive.stat()
            self.assertEqual(str(archive.resolve()), migrated)
            self.assertEqual(str(archive.resolve()), loaded["archive_root"])
            self.assertEqual(before.st_ino, after.st_ino)
            self.assertEqual(before.st_mtime_ns, after.st_mtime_ns)
            self.assertIn("schema_version = 2", config.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
