from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from settings_backend import load_settings, save_settings


class SettingsBackendTests(unittest.TestCase):
    def test_gpu_and_display_roundtrip_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": td}, clear=False):
            path = save_settings({
                "gpu_pci": "0000:03:00.0",
                "display_backend": "xwayland",
            })
            loaded = load_settings()
            self.assertEqual(Path(td) / "bottles-retro-cd" / "config.toml", path)
            self.assertEqual("0000:03:00.0", loaded["gpu_pci"])
            self.assertEqual("xwayland", loaded["display_backend"])
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE(path.parent.stat().st_mode))

    def test_invalid_config_falls_back_safely(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": td}, clear=False):
            path = Path(td) / "bottles-retro-cd" / "config.toml"
            path.parent.mkdir(parents=True)
            path.write_text("not valid = [", encoding="utf-8")
            loaded = load_settings()
            self.assertEqual("", loaded["gpu_pci"])
            self.assertEqual("auto", loaded["display_backend"])

    def test_unknown_display_backend_is_normalized_to_auto(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": td}, clear=False):
            path = Path(td) / "bottles-retro-cd" / "config.toml"
            path.parent.mkdir(parents=True)
            path.write_text(
                'schema_version = 1\ngpu_pci = ""\ndisplay_backend = "future-backend"\n',
                encoding="utf-8",
            )
            self.assertEqual("auto", load_settings()["display_backend"])


if __name__ == "__main__":
    unittest.main()
