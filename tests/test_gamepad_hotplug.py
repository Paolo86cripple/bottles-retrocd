from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

import gamepad_hotplug as hotplug
from gamepad_backend import GamepadDevice, GamepadProbe


class GamepadHotplugTests(unittest.TestCase):
    def test_device_node_map_contains_only_exact_nodes(self):
        device = GamepadDevice(
            name="Xbox",
            js_node="/dev/input/js0",
            event_nodes=("/dev/input/event24",),
        )
        self.assertEqual(
            {"js0": "/dev/input/js0", "event24": "/dev/input/event24"},
            hotplug.device_node_map((device,)),
        )

    def test_device_node_map_rejects_outside_input(self):
        device = GamepadDevice(
            name="bad",
            js_node="/dev/hidraw0",
            event_nodes=("/dev/input/event24",),
        )
        with self.assertRaisesRegex(RuntimeError, "fuori da /dev/input"):
            hotplug.device_node_map((device,))

    def test_validate_exact_probe_rejects_unrelated_or_hidraw(self):
        probe = GamepadProbe(
            input_dir_visible=True,
            nodes={
                "js0": (True, True),
                "event24": (True, True),
                "event3": (True, True),
            },
            hidraw_nodes=("/dev/hidraw0",),
        )
        with self.assertRaisesRegex(RuntimeError, "estranei=event3.*hidraw"):
            hotplug.validate_exact_probe({"js0", "event24"}, probe)

    def test_validate_exact_probe_accepts_disconnect_empty_surface(self):
        probe = GamepadProbe(
            input_dir_visible=True,
            nodes={},
            hidraw_nodes=(),
        )
        self.assertEqual((), hotplug.validate_exact_probe(set(), probe))

    def test_reconcile_rebuilds_surface_and_verifies(self):
        device = GamepadDevice(
            name="Xbox",
            js_node="/dev/input/js0",
            event_nodes=("/dev/input/event24",),
        )
        before = GamepadProbe(
            input_dir_visible=True,
            nodes={"js0": (True, True), "event24": (True, True)},
            hidraw_nodes=(),
        )
        after = GamepadProbe(
            input_dir_visible=True,
            nodes={"js0": (True, True), "event24": (True, True)},
            hidraw_nodes=(),
        )
        proc = SimpleNamespace(returncode=0, stdout="BOUND=event24\nBOUND=js0\n")
        with (
            mock.patch.object(hotplug.SandboxBackend, "running", return_value=True),
            mock.patch.object(hotplug, "detect_host_gamepads", return_value=(device,)),
            mock.patch.object(hotplug, "attached_probe", side_effect=(before, after)),
            mock.patch.object(hotplug.Path, "is_file", return_value=True),
            mock.patch.object(hotplug.subprocess, "run", return_value=proc) as run,
        ):
            result = hotplug.reconcile_gamepads("Bottles")
        self.assertEqual(("event24", "js0"), result.nodes)
        args = run.call_args.args[0]
        self.assertIn("--remove", args)
        self.assertIn("event24", args)
        self.assertIn("--bind", args)
        self.assertIn("/dev/input/js0", args)

    def test_initial_activation_is_non_destructive(self):
        device = GamepadDevice(
            name="Xbox",
            js_node="/dev/input/js0",
            event_nodes=("/dev/input/event24",),
        )
        probe = GamepadProbe(
            input_dir_visible=True,
            nodes={"js0": (True, True), "event24": (True, True)},
            hidraw_nodes=(),
        )
        proc = SimpleNamespace(returncode=0, stdout="BOUND=event24\nBOUND=js0\n")
        with (
            mock.patch.object(hotplug.SandboxBackend, "running", return_value=True),
            mock.patch.object(hotplug, "detect_host_gamepads", return_value=(device,)),
            mock.patch.object(hotplug, "attached_probe", side_effect=(probe, probe)),
            mock.patch.object(hotplug.Path, "is_file", return_value=True),
            mock.patch.object(hotplug.subprocess, "run", return_value=proc) as run,
        ):
            hotplug.reconcile_gamepads("Bottles", replace_existing=False)
        args = run.call_args.args[0]
        self.assertNotIn("--remove", args)
        self.assertIn("--bind", args)


if __name__ == "__main__":
    unittest.main()
