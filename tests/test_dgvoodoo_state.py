from __future__ import annotations

import hashlib
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from dgvoodoo_backend import BottleInfo, ReleaseInfo, Wrapper, install_wrappers, uninstall_wrappers
from dgvoodoo_state import inspect_installation


class DgVoodooStateTests(unittest.TestCase):
    @staticmethod
    def _pe(path: Path, machine: int = 0x014C) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = bytearray(256)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        data[0x80:0x84] = b"PE\x00\x00"
        struct.pack_into("<H", data, 0x84, machine)
        path.write_bytes(data)
        return path

    @staticmethod
    def _bottle(root: Path) -> BottleInfo:
        bottle_root = root / "bottle"
        drive = bottle_root / "drive_c"
        drive.mkdir(parents=True)
        (bottle_root / "bottle.yml").write_text("Name: Test\n", encoding="utf-8")
        return BottleInfo("Test", bottle_root.resolve(), drive.resolve())

    @staticmethod
    def _archive(path: Path) -> tuple[Path, ReleaseInfo]:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("dgVoodoo.conf", b"[General]\n")
            zf.writestr("dgVoodooCpl.exe", b"MZ-control-panel")
            zf.writestr("MS/x86/DDraw.dll", b"ddraw-x86")
        payload = path.read_bytes()
        return path, ReleaseInfo(
            tag="v2.87.4",
            version="2.87.4",
            asset_name="dgVoodoo2_87_4.zip",
            download_url="https://github.com/dege-diosg/dgVoodoo2/releases/download/v2.87.4/dgVoodoo2_87_4.zip",
            sha256=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )

    def test_inactive_installed_modified_and_restored(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle = self._bottle(root)
            exe = self._pe(bottle.drive_c / "Game/game.exe")
            archive, release = self._archive(root / "dg.zip")
            data_root = root / "manager"

            state = inspect_installation(bottle, exe, data_root=data_root)
            self.assertEqual("inactive", state.state)
            self.assertEqual("x86", state.arch)

            install_wrappers(
                archive,
                release,
                bottle,
                exe,
                [Wrapper.DDRAW],
                data_root=data_root,
            )
            state = inspect_installation(bottle, exe, data_root=data_root)
            self.assertEqual("installed", state.state)
            self.assertEqual("2.87.4", state.version)
            self.assertEqual((Wrapper.DDRAW,), state.wrappers)
            self.assertEqual("ddraw=n,b", state.wine_overrides)
            self.assertIsNotNone(state.control_panel)
            self.assertFalse(state.problems)

            (exe.parent / "DDraw.dll").write_bytes(b"tampered")
            state = inspect_installation(bottle, exe, data_root=data_root)
            self.assertEqual("modified", state.state)
            self.assertTrue(any("modificato" in item for item in state.problems))

            (exe.parent / "DDraw.dll").write_bytes(b"ddraw-x86")
            uninstall_wrappers(bottle, exe, data_root=data_root)
            state = inspect_installation(bottle, exe, data_root=data_root)
            self.assertEqual("inactive", state.state)


if __name__ == "__main__":
    unittest.main()
