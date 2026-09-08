from __future__ import annotations

import json
import struct
import tempfile
import unittest
from pathlib import Path

from dgvoodoo_backend import BottleInfo, DgVoodooError
from dgvoodoo_policy import ensure_unique_managed_app_name


class DgVoodooPolicyTests(unittest.TestCase):
    @staticmethod
    def _pe(path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = bytearray(256)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        data[0x80:0x84] = b"PE\x00\x00"
        struct.pack_into("<H", data, 0x84, 0x014C)
        path.write_bytes(data)
        return path

    def test_same_basename_in_same_bottle_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle_root = root / "bottle"
            drive = bottle_root / "drive_c"
            drive.mkdir(parents=True)
            (bottle_root / "bottle.yml").write_text("Name: Test\n", encoding="utf-8")
            bottle = BottleInfo("Test", bottle_root.resolve(), drive.resolve())
            first = self._pe(drive / "A/game.exe")
            second = self._pe(drive / "B/game.exe")
            data_root = root / "manager"
            state_dir = data_root / "activations" / "one"
            state_dir.mkdir(parents=True)
            (state_dir / "state.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "status": "active",
                    "bottle_root": str(bottle.root.resolve()),
                    "target_exe": str(first.resolve()),
                    "app_name": "game.exe",
                    "overrides": ["ddraw"],
                    "previous": {"ddraw": None},
                    "expected": {"ddraw": "n,b"},
                }),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(DgVoodooError, "basename"):
                ensure_unique_managed_app_name(bottle, second, data_root=data_root)

    def test_different_basename_or_bottle_is_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle_root = root / "bottle"
            drive = bottle_root / "drive_c"
            drive.mkdir(parents=True)
            (bottle_root / "bottle.yml").write_text("Name: Test\n", encoding="utf-8")
            bottle = BottleInfo("Test", bottle_root.resolve(), drive.resolve())
            first = self._pe(drive / "A/game.exe")
            second = self._pe(drive / "B/other.exe")
            data_root = root / "manager"
            state_dir = data_root / "activations" / "one"
            state_dir.mkdir(parents=True)
            (state_dir / "state.json").write_text(
                json.dumps({
                    "schema_version": 1,
                    "status": "active",
                    "bottle_root": str(bottle.root.resolve()),
                    "target_exe": str(first.resolve()),
                    "app_name": "game.exe",
                }),
                encoding="utf-8",
            )
            ensure_unique_managed_app_name(bottle, second, data_root=data_root)


if __name__ == "__main__":
    unittest.main()
