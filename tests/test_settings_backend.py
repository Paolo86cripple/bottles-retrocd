from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from settings_backend import load_settings, save_settings


class SettingsBackendTests(unittest.TestCase):
    def test_gpu_pci_roundtrip_and_private_permissions(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": td}, clear=False):
            path = save_settings({"gpu_pci": "0000:03:00.0"})
            self.assertEqual(Path(td) / "bottles-retro-cd" / "config.toml", path)
            self.assertEqual("0000:03:00.0", load_settings()["gpu_pci"])
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE(path.parent.stat().st_mode))

    def test_invalid_config_falls_back_safely(self):
        with tempfile.TemporaryDirectory() as td, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": td}, clear=False):
            path = Path(td) / "bottles-retro-cd" / "config.toml"
            path.parent.mkdir(parents=True)
            path.write_text("not valid = [", encoding="utf-8")
            self.assertEqual("", load_settings()["gpu_pci"])


if __name__ == "__main__":
    unittest.main()
