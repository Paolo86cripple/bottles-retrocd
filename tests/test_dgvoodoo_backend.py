from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path

from dgvoodoo_backend import (
    BottleInfo,
    DgVoodooError,
    ReleaseInfo,
    TargetArch,
    Wrapper,
    detect_pe_arch,
    discover_bottles,
    install_wrappers,
    parse_release_metadata,
    uninstall_wrappers,
    wine_overrides_value,
)


class DgVoodooBackendTests(unittest.TestCase):
    def _pe(self, path: Path, machine: int) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = bytearray(256)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        data[0x80:0x84] = b"PE\x00\x00"
        struct.pack_into("<H", data, 0x84, machine)
        path.write_bytes(data)
        return path

    def _bottle(self, root: Path, name: str = "Noir") -> BottleInfo:
        bottle_root = root / ".local/share/bottles/bottles" / name
        drive = bottle_root / "drive_c"
        drive.mkdir(parents=True)
        (bottle_root / "bottle.yml").write_text("Name: Noir\n", encoding="utf-8")
        return BottleInfo(name, bottle_root.resolve(), drive.resolve())

    def _archive(self, path: Path, *, malicious: bool = False) -> tuple[Path, ReleaseInfo]:
        members = {
            "dgVoodoo.conf": b"[General]\nOutputAPI = bestavailable\n",
            "dgVoodooCpl.exe": b"MZ-cpl",
            "MS/x86/DDraw.dll": b"ddraw-x86",
            "MS/x86/D3DImm.dll": b"d3dimm-x86",
            "MS/x86/D3DIM700.dll": b"d3dim700-x86",
            "MS/x86/D3D8.dll": b"d3d8-x86",
            "MS/x86/D3D9.dll": b"d3d9-x86",
            "3Dfx/x86/Glide.dll": b"glide-x86",
            "3Dfx/x86/Glide2x.dll": b"glide2x-x86",
            "3Dfx/x86/Glide3x.dll": b"glide3x-x86",
            "3Dfx/x86/Napalm/Glide3x.dll": b"napalm-x86",
            "MS/x64/DDraw.dll": b"ddraw-x64",
            "MS/x64/D3D9.dll": b"d3d9-x64",
        }
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, data in members.items():
                zf.writestr(name, data)
            if malicious:
                zf.writestr("../escape.dll", b"bad")
        payload = path.read_bytes()
        return path, ReleaseInfo(
            tag="v2.87.4",
            version="2.87.4",
            asset_name="dgVoodoo2_87_4.zip",
            download_url="https://github.com/dege-diosg/dgVoodoo2/releases/download/v2.87.4/dgVoodoo2_87_4.zip",
            sha256=hashlib.sha256(payload).hexdigest(),
            size=len(payload),
        )

    def test_parse_official_release_metadata(self):
        raw = {
            "tag_name": "v2.87.4",
            "draft": False,
            "prerelease": False,
            "assets": [
                {
                    "name": "dgVoodoo2_87_4.zip",
                    "browser_download_url": "https://github.com/dege-diosg/dgVoodoo2/releases/download/v2.87.4/dgVoodoo2_87_4.zip",
                    "digest": "sha256:" + "ab" * 32,
                    "size": 9235426,
                },
                {
                    "name": "dgVoodoo2_87_4_dbg.zip",
                    "browser_download_url": "https://github.com/dege-diosg/dgVoodoo2/releases/download/v2.87.4/dgVoodoo2_87_4_dbg.zip",
                    "digest": "sha256:" + "cd" * 32,
                    "size": 1000,
                },
            ],
        }
        release = parse_release_metadata(json.dumps(raw).encode())
        self.assertEqual("2.87.4", release.version)
        self.assertEqual("dgVoodoo2_87_4.zip", release.asset_name)
        self.assertEqual("ab" * 32, release.sha256)

    def test_release_metadata_requires_digest(self):
        raw = {
            "tag_name": "v2.87.4",
            "draft": False,
            "prerelease": False,
            "assets": [{
                "name": "dgVoodoo2_87_4.zip",
                "browser_download_url": "https://github.com/dege-diosg/dgVoodoo2/releases/download/v2.87.4/dgVoodoo2_87_4.zip",
                "size": 1234,
            }],
        }
        with self.assertRaises(DgVoodooError):
            parse_release_metadata(json.dumps(raw).encode())

    def test_pe_arch_detection(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertEqual(TargetArch.X86, detect_pe_arch(self._pe(root / "x86.exe", 0x014C)))
            self.assertEqual(TargetArch.X64, detect_pe_arch(self._pe(root / "x64.exe", 0x8664)))
            with self.assertRaises(DgVoodooError):
                detect_pe_arch(self._pe(root / "arm.exe", 0xAA64))

    def test_discovers_only_normal_bottles(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            bottle = self._bottle(home, "Good")
            bad = home / ".local/share/bottles/bottles/Bad"
            (bad / "drive_c").mkdir(parents=True)
            found = discover_bottles(home)
            self.assertEqual(("Good",), tuple(item.name for item in found))
            self.assertEqual(bottle.drive_c, found[0].drive_c)

    def test_install_preserves_config_and_restores_existing_dll(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle = self._bottle(root)
            game = bottle.drive_c / "Games/Noir"
            exe = self._pe(game / "noir.exe", 0x014C)
            (game / "DDraw.dll").write_bytes(b"original-ddraw")
            (game / "dgVoodoo.conf").write_text("custom=true\n", encoding="utf-8")
            archive, release = self._archive(root / "dg.zip")
            data_root = root / "manager"

            report = install_wrappers(
                archive,
                release,
                bottle,
                exe,
                [Wrapper.DDRAW, Wrapper.D3DIMM],
                data_root=data_root,
            )
            self.assertEqual(TargetArch.X86, report.arch)
            self.assertEqual(b"ddraw-x86", (game / "DDraw.dll").read_bytes())
            self.assertEqual(b"d3dimm-x86", (game / "D3DImm.dll").read_bytes())
            self.assertEqual("custom=true\n", (game / "dgVoodoo.conf").read_text())
            self.assertTrue((game / "dgVoodooCpl.exe").is_file())
            manifest = json.loads(report.manifest_path.read_text())
            self.assertEqual("ddraw=n,b;d3dimm=n,b", manifest["wine_overrides"])
            self.assertIn("dgVoodoo.conf", manifest["preserved_files"])

            restored = uninstall_wrappers(bottle, exe, data_root=data_root)
            self.assertIn(game / "DDraw.dll", restored)
            self.assertEqual(b"original-ddraw", (game / "DDraw.dll").read_bytes())
            self.assertFalse((game / "D3DImm.dll").exists())
            self.assertFalse((game / "dgVoodooCpl.exe").exists())
            self.assertEqual("custom=true\n", (game / "dgVoodoo.conf").read_text())

    def test_x64_selects_x64_payload(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle = self._bottle(root)
            exe = self._pe(bottle.drive_c / "Game64/game.exe", 0x8664)
            archive, release = self._archive(root / "dg.zip")
            report = install_wrappers(
                archive, release, bottle, exe, [Wrapper.D3D9], data_root=root / "manager"
            )
            self.assertEqual(TargetArch.X64, report.arch)
            self.assertEqual(b"d3d9-x64", (exe.parent / "D3D9.dll").read_bytes())

    def test_executable_outside_drive_c_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle = self._bottle(root)
            exe = self._pe(root / "outside.exe", 0x014C)
            archive, release = self._archive(root / "dg.zip")
            with self.assertRaisesRegex(DgVoodooError, "fuori da drive_c"):
                install_wrappers(
                    archive, release, bottle, exe, [Wrapper.DDRAW], data_root=root / "manager"
                )

    def test_zip_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle = self._bottle(root)
            exe = self._pe(bottle.drive_c / "Game/game.exe", 0x014C)
            archive, release = self._archive(root / "bad.zip", malicious=True)
            with self.assertRaisesRegex(DgVoodooError, "Path ZIP"):
                install_wrappers(
                    archive, release, bottle, exe, [Wrapper.DDRAW], data_root=root / "manager"
                )

    def test_regular_and_napalm_glide3_conflict(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle = self._bottle(root)
            exe = self._pe(bottle.drive_c / "Game/game.exe", 0x014C)
            archive, release = self._archive(root / "dg.zip")
            with self.assertRaisesRegex(DgVoodooError, "ambigua"):
                install_wrappers(
                    archive,
                    release,
                    bottle,
                    exe,
                    [Wrapper.GLIDE3X, Wrapper.GLIDE3X_NAPALM],
                    data_root=root / "manager",
                )

    def test_modified_managed_file_blocks_uninstall(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle = self._bottle(root)
            exe = self._pe(bottle.drive_c / "Game/game.exe", 0x014C)
            archive, release = self._archive(root / "dg.zip")
            data_root = root / "manager"
            install_wrappers(
                archive, release, bottle, exe, [Wrapper.DDRAW], data_root=data_root
            )
            (exe.parent / "DDraw.dll").write_bytes(b"changed-after-install")
            with self.assertRaisesRegex(DgVoodooError, "modificato dopo"):
                uninstall_wrappers(bottle, exe, data_root=data_root)
            self.assertEqual(b"changed-after-install", (exe.parent / "DDraw.dll").read_bytes())

    def test_existing_destination_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle = self._bottle(root)
            exe = self._pe(bottle.drive_c / "Game/game.exe", 0x014C)
            outside = root / "outside.dll"
            outside.write_bytes(b"outside")
            os.symlink(outside, exe.parent / "DDraw.dll")
            archive, release = self._archive(root / "dg.zip")
            with self.assertRaisesRegex(DgVoodooError, "symlink"):
                install_wrappers(
                    archive, release, bottle, exe, [Wrapper.DDRAW], data_root=root / "manager"
                )
            self.assertEqual(b"outside", outside.read_bytes())

    def test_wine_override_value_is_minimal(self):
        self.assertEqual(
            "ddraw=n,b;d3d8=n,b;glide2x=n,b",
            wine_overrides_value([Wrapper.DDRAW, Wrapper.D3D8, Wrapper.GLIDE2X]),
        )


if __name__ == "__main__":
    unittest.main()
