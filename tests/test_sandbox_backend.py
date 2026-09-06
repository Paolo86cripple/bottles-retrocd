from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sandbox_backend import SandboxBackend  # noqa: E402


class SandboxBackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.xdg = Path(self.tmp.name) / "xdg"
        self.rw = Path(self.tmp.name) / "rw"
        self.ro = Path(self.tmp.name) / "ro"
        self.rw.mkdir()
        self.ro.mkdir()

        self.env = patch.dict(os.environ, {"XDG_DATA_HOME": str(self.xdg)})
        self.env.start()
        self.addCleanup(self.env.stop)

        self.backend = SandboxBackend("BottlesTest")
        self.backend.instance_dir.mkdir(parents=True)
        self.backend.private_home.mkdir()
        self.backend.services_path.write_text(
            "[common]\nexecutable_name = \"/usr/bin/bottles\"\n\n"
            "[wayland]\n\n"
            "[root_share]\npaths = []\nread_only_paths = []\n",
            encoding="utf-8",
        )

    def test_set_whitelist_preserves_other_sections_and_creates_backup(self):
        with patch.object(self.backend, "running", return_value=False):
            backup = self.backend.set_whitelist([str(self.rw)], [str(self.ro)])
        cfg = self.backend.config()
        self.assertEqual(cfg["common"]["executable_name"], "/usr/bin/bottles")
        self.assertIn("wayland", cfg)
        self.assertEqual(cfg["root_share"]["paths"], [str(self.rw.resolve())])
        self.assertEqual(cfg["root_share"]["read_only_paths"], [str(self.ro.resolve())])
        self.assertTrue(backup.exists())

    def test_rejects_root(self):
        with patch.object(self.backend, "running", return_value=False):
            with self.assertRaises(RuntimeError):
                self.backend.set_whitelist(["/"], [])

    def test_rejects_nested_binds(self):
        child = self.rw / "child"
        child.mkdir()
        with patch.object(self.backend, "running", return_value=False):
            with self.assertRaises(RuntimeError):
                self.backend.set_whitelist([str(self.rw)], [str(child)])

    def test_restore_backup(self):
        original = self.backend.services_path.read_text(encoding="utf-8")
        with patch.object(self.backend, "running", return_value=False):
            self.backend.set_whitelist([str(self.rw)], [str(self.ro)])
            self.backend.restore_backup()
        self.assertEqual(self.backend.services_path.read_text(encoding="utf-8"), original)


if __name__ == "__main__":
    unittest.main()
