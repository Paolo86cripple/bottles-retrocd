from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from bottles_storage import discover_bottles, read_custom_bottles_path, resolve_bottles_storage
from dgvoodoo_backend import DgVoodooError


class BottlesStorageTests(unittest.TestCase):
    def _private_home(self, root: Path) -> Path:
        home = root / "private-home"
        (home / ".local/share/bottles").mkdir(parents=True)
        return home

    def _bottle(self, root: Path, name: str) -> Path:
        bottle = root / name
        (bottle / "drive_c").mkdir(parents=True)
        (bottle / "bottle.yml").write_text("Name: Test\n", encoding="utf-8")
        return bottle

    def test_default_storage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = self._private_home(root)
            bottles_root = home / ".local/share/bottles/bottles"
            self._bottle(bottles_root, "DefaultBottle")
            storage, bottles = discover_bottles(home)
            self.assertEqual("default", storage.source)
            self.assertEqual(bottles_root, storage.root)
            self.assertEqual(("DefaultBottle",), tuple(item.name for item in bottles))

    def test_custom_storage_plain_yaml(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = self._private_home(root)
            custom = root / "EGLLibrary/abandonpfx"
            self._bottle(custom, "RetroCD-dgVoodoo-Test")
            (home / ".local/share/bottles/data.yml").write_text(
                f"custom_bottles_path: {custom}\nfunding_prompt_count: 1\n",
                encoding="utf-8",
            )
            storage, bottles = discover_bottles(home)
            self.assertEqual("custom", storage.source)
            self.assertEqual(custom.resolve(), storage.root)
            self.assertEqual(custom, storage.configured_custom)
            self.assertEqual(("RetroCD-dgVoodoo-Test",), tuple(item.name for item in bottles))

    def test_custom_storage_quoted_yaml(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = self._private_home(root)
            custom = root / "Bottle Storage"
            custom.mkdir()
            (home / ".local/share/bottles/data.yml").write_text(
                f"custom_bottles_path: \"{custom}\"\n",
                encoding="utf-8",
            )
            self.assertEqual(custom, read_custom_bottles_path(home))
            self.assertEqual(custom.resolve(), resolve_bottles_storage(home).root)

    def test_relative_custom_storage_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            home = self._private_home(Path(td))
            (home / ".local/share/bottles/data.yml").write_text(
                "custom_bottles_path: relative/path\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(DgVoodooError, "relativo"):
                resolve_bottles_storage(home)

    def test_duplicate_custom_storage_key_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = self._private_home(root)
            one = root / "one"
            two = root / "two"
            one.mkdir()
            two.mkdir()
            (home / ".local/share/bottles/data.yml").write_text(
                f"custom_bottles_path: {one}\ncustom_bottles_path: {two}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(DgVoodooError, "più custom_bottles_path"):
                resolve_bottles_storage(home)

    def test_unrelated_directory_is_not_a_bottle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            home = self._private_home(root)
            custom = root / "custom"
            custom.mkdir()
            (custom / "Random").mkdir()
            (home / ".local/share/bottles/data.yml").write_text(
                f"custom_bottles_path: {custom}\n",
                encoding="utf-8",
            )
            _storage, bottles = discover_bottles(home)
            self.assertEqual((), bottles)


if __name__ == "__main__":
    unittest.main()
