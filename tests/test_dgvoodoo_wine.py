from __future__ import annotations

import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from dgvoodoo_backend import BottleInfo, DgVoodooError
from dgvoodoo_wine import (
    activate_app_overrides,
    activation_status,
    check_program_environment_conflicts,
    deactivate_app_overrides,
    parse_reg_query,
    tamper_refusal_test,
)


class FakeBottlesRunner:
    def __init__(self):
        self.registry: dict[str, str] = {}
        self.programs: list[dict] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        if "programs" in args and "-j" in args:
            payload = json.dumps(self.programs, separators=(",", ":"))
            return subprocess.CompletedProcess(args, 0, stdout=f"warning before\n{payload}No children found. Terminating.\n")
        if "shell" in args:
            command = args[args.index("-i") + 1]
            marker = "/v "
            name = command.split(marker, 1)[1].strip().casefold()
            if name not in self.registry:
                return subprocess.CompletedProcess(
                    args,
                    0,
                    stdout="Command exited with status 1.reg: Unable to find the specified registry key\n",
                )
            value = self.registry[name]
            return subprocess.CompletedProcess(
                args,
                0,
                stdout=(
                    "Bottles runtime was requested but not found\n"
                    "HKEY_CURRENT_USER\\Software\\Wine\\AppDefaults\\probe.exe\\DllOverrides\n"
                    f"    {name}    REG_SZ    {value}\n"
                    "No children found. Terminating.\n"
                ),
            )
        if "reg" in args:
            action = args[args.index("reg") + 1]
            name = args[args.index("-v") + 1].casefold()
            if action == "add":
                self.registry[name] = args[args.index("-d") + 1]
            elif action == "del":
                self.registry.pop(name, None)
            else:
                raise AssertionError(f"unexpected reg action {action}")
            return subprocess.CompletedProcess(args, 0, stdout="")
        raise AssertionError(f"unexpected command: {args}")


class DgVoodooWineTests(unittest.TestCase):
    def _bottle(self, root: Path) -> tuple[BottleInfo, Path]:
        bottle_root = root / "bottle"
        drive = bottle_root / "drive_c"
        exe = drive / "Probe/probe.exe"
        exe.parent.mkdir(parents=True)
        data = bytearray(256)
        data[:2] = b"MZ"
        struct.pack_into("<I", data, 0x3C, 0x80)
        data[0x80:0x84] = b"PE\x00\x00"
        struct.pack_into("<H", data, 0x84, 0x014C)
        exe.write_bytes(data)
        (bottle_root / "bottle.yml").write_text("Name: test\n", encoding="utf-8")
        return BottleInfo("test", bottle_root.resolve(), drive.resolve()), exe.resolve()

    def test_parse_realistic_absent_and_present_outputs(self):
        absent = "Command exited with status 1.reg: Unable to find the specified registry key\n"
        self.assertIsNone(parse_reg_query(absent, "ddraw"))
        present = (
            "noise\nHKEY_CURRENT_USER\\Software\\Wine\\AppDefaults\\probe.exe\\DllOverrides\n"
            "    ddraw    REG_SZ    n,b\nnoise\n"
        )
        self.assertEqual("n,b", parse_reg_query(present, "ddraw"))

    def test_activate_and_restore_absent_value(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle, exe = self._bottle(root)
            runner = FakeBottlesRunner()
            state_root = root / "manager"
            status = activate_app_overrides(
                bottle, exe, ["ddraw"], data_root=state_root, runner=runner
            )
            self.assertEqual("active", status.state)
            self.assertEqual("n,b", runner.registry["ddraw"])
            self.assertEqual("active", activation_status(bottle, exe, data_root=state_root).state)
            final = deactivate_app_overrides(
                bottle, exe, data_root=state_root, runner=runner
            )
            self.assertEqual("inactive", final.state)
            self.assertNotIn("ddraw", runner.registry)
            self.assertEqual("inactive", activation_status(bottle, exe, data_root=state_root).state)

    def test_existing_value_is_restored_exactly(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle, exe = self._bottle(root)
            runner = FakeBottlesRunner()
            runner.registry["ddraw"] = "b,n"
            state_root = root / "manager"
            activate_app_overrides(
                bottle, exe, ["ddraw"], data_root=state_root, runner=runner
            )
            self.assertEqual("n,b", runner.registry["ddraw"])
            deactivate_app_overrides(bottle, exe, data_root=state_root, runner=runner)
            self.assertEqual("b,n", runner.registry["ddraw"])

    def test_tamper_refusal_preserves_active_transaction(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle, exe = self._bottle(root)
            runner = FakeBottlesRunner()
            state_root = root / "manager"
            activate_app_overrides(
                bottle, exe, ["ddraw"], data_root=state_root, runner=runner
            )
            message = tamper_refusal_test(
                bottle, exe, "ddraw", data_root=state_root, runner=runner
            )
            self.assertIn("modificato dopo", message)
            self.assertEqual("n,b", runner.registry["ddraw"])
            self.assertEqual("active", activation_status(bottle, exe, data_root=state_root).state)
            deactivate_app_overrides(bottle, exe, data_root=state_root, runner=runner)

    def test_program_environment_collision_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle, exe = self._bottle(root)
            runner = FakeBottlesRunner()
            runner.programs = [{
                "path": r"C:\\Probe\\probe.exe",
                "environment": {"WINEDLLOVERRIDES": "version=n,b;ddraw=b"},
            }]
            with self.assertRaisesRegex(DgVoodooError, "precedenza"):
                check_program_environment_conflicts(
                    bottle, exe, ["ddraw"], runner=runner
                )

    def test_unrelated_program_override_does_not_block(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bottle, exe = self._bottle(root)
            runner = FakeBottlesRunner()
            runner.programs = [{
                "path": r"C:\\Probe\\probe.exe",
                "environment": {"WINEDLLOVERRIDES": "version=n,b"},
            }]
            check_program_environment_conflicts(bottle, exe, ["ddraw"], runner=runner)


if __name__ == "__main__":
    unittest.main()
