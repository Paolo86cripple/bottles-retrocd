from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import gamepad_backend as gamepad
from gamepad_backend import (
    GamepadBackend,
    GamepadDevice,
    parse_gamepad_probe,
)


class GamepadBackendTests(unittest.TestCase):
    def make_backend(self, root: Path, text: str) -> GamepadBackend:
        services = root / "services.toml"
        services.write_text(text, encoding="utf-8")
        backend = GamepadBackend("Bottles", services_path=services)
        self.addCleanup(lambda: None)
        return backend

    def test_enable_disable_preserves_other_services_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            original = (
                "[x11]\n"
                "\n"
                "[wayland]\n"
                "\n"
                "[root_share]\n"
                'paths = ["/tmp/rw"]\n'
                "read_only_paths = []\n"
            )
            backend = self.make_backend(root, original)
            with mock.patch.object(backend, "_running", return_value=False):
                backup = backend.set_enabled(True)
                self.assertTrue(backend.enabled())
                self.assertEqual(backend.backup_path, backup)
                self.assertEqual(original, backend.backup_path.read_text(encoding="utf-8"))
                enabled_text = backend.services_path.read_text(encoding="utf-8")
                self.assertIn("[x11]", enabled_text)
                self.assertIn("[wayland]", enabled_text)
                self.assertIn("[root_share]", enabled_text)
                self.assertIn("[joystick]", enabled_text)

                backend.set_enabled(False)
                self.assertFalse(backend.enabled())
                disabled_text = backend.services_path.read_text(encoding="utf-8")
                self.assertIn("[x11]", disabled_text)
                self.assertIn("[wayland]", disabled_text)
                self.assertIn("[root_share]", disabled_text)
                self.assertNotIn("[joystick]", disabled_text)

    def test_noop_does_not_rewrite_profile(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            backend = self.make_backend(root, "[joystick]\n\n[x11]\n")
            before = backend.services_path.read_bytes()
            with mock.patch.object(backend, "_running", return_value=False):
                self.assertIsNone(backend.set_enabled(True))
            self.assertEqual(before, backend.services_path.read_bytes())
            self.assertFalse(backend.backup_path.exists())

    def test_profile_change_is_refused_while_instance_runs(self):
        with tempfile.TemporaryDirectory() as td:
            backend = self.make_backend(Path(td), "[x11]\n")
            with mock.patch.object(backend, "_running", return_value=True):
                with self.assertRaisesRegex(RuntimeError, "Chiudi Bottles/Bubblejail"):
                    backend.set_enabled(True)

    def test_probe_parser_tracks_read_write_and_hidraw(self):
        probe = parse_gamepad_probe(
            "\n".join(
                [
                    "GP_INPUT_DIR=1",
                    "GP_NODE=event24|1|1",
                    "GP_NODE=js0|1|0",
                    "GP_HIDRAW=/dev/hidraw7",
                ]
            )
        )
        self.assertTrue(probe.input_dir_visible)
        self.assertEqual((True, True), probe.nodes["event24"])
        self.assertEqual((True, False), probe.nodes["js0"])
        self.assertEqual(("/dev/hidraw7",), probe.hidraw_nodes)

    def test_runtime_probe_accepts_only_expected_gamepad_nodes(self):
        with tempfile.TemporaryDirectory() as td:
            backend = self.make_backend(Path(td), "[joystick]\n")
            device = GamepadDevice(
                name="Xbox One Controller",
                js_node="/dev/input/js0",
                event_nodes=("/dev/input/event24",),
            )
            proc = SimpleNamespace(
                returncode=0,
                stdout=(
                    "GP_INPUT_DIR=1\n"
                    "GP_NODE=event24|1|1\n"
                    "GP_NODE=js0|1|0\n"
                ),
            )
            with (
                mock.patch.object(backend, "_running", return_value=False),
                mock.patch.object(gamepad, "detect_host_gamepads", return_value=(device,)),
                mock.patch.object(gamepad, "run_cmd", return_value=proc),
            ):
                result = backend.test()
            self.assertIn("[PASS] soli nodi gamepad attesi visibili: event24, js0", result)
            self.assertIn("Xbox One Controller", result)
            self.assertIn("[PASS] /dev/hidraw* non esposto", result)

    def test_runtime_probe_rejects_unrelated_input_or_hidraw(self):
        with tempfile.TemporaryDirectory() as td:
            backend = self.make_backend(Path(td), "[joystick]\n")
            device = GamepadDevice(
                name="Xbox One Controller",
                js_node="/dev/input/js0",
                event_nodes=("/dev/input/event24",),
            )
            proc = SimpleNamespace(
                returncode=0,
                stdout=(
                    "GP_INPUT_DIR=1\n"
                    "GP_NODE=event24|1|1\n"
                    "GP_NODE=js0|1|0\n"
                    "GP_NODE=event3|1|1\n"
                    "GP_HIDRAW=/dev/hidraw0\n"
                ),
            )
            with (
                mock.patch.object(backend, "_running", return_value=False),
                mock.patch.object(gamepad, "detect_host_gamepads", return_value=(device,)),
                mock.patch.object(gamepad, "run_cmd", return_value=proc),
            ):
                with self.assertRaisesRegex(RuntimeError, "event3.*hidraw"):
                    backend.test()


if __name__ == "__main__":
    unittest.main()
