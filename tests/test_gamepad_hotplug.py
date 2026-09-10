from __future__ import annotations

import socket
import struct
import unittest
from types import SimpleNamespace
from unittest import mock

import gamepad_hotplug as hotplug
import gamepad_ns_entry as ns_entry
import gamepad_ns_helper as ns_helper
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

    def test_reconcile_rebuilds_surface_notifies_udev_and_verifies(self):
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
        proc = SimpleNamespace(
            returncode=0,
            stdout=(
                "UDEV_REMOVE=event24\n"
                "UDEV_REMOVE=js0\n"
                "BOUND=event24\n"
                "BOUND=js0\n"
                "UDEV_ADD=event24\n"
                "UDEV_ADD=js0\n"
            ),
        )
        with (
            mock.patch.object(hotplug.SandboxBackend, "running", return_value=True),
            mock.patch.object(hotplug, "detect_host_gamepads", return_value=(device,)),
            mock.patch.object(hotplug, "attached_probe", side_effect=(before, after)),
            mock.patch.object(hotplug.Path, "is_file", return_value=True),
            mock.patch.object(hotplug.subprocess, "run", return_value=proc) as run,
        ):
            result = hotplug.reconcile_gamepads("Bottles")
        self.assertEqual(("event24", "js0"), result.nodes)
        self.assertTrue(result.udev_notified)
        self.assertIn("udev=notified", result.format("evento add/remove/reconnect"))
        args = run.call_args.args[0]
        self.assertIn("--notify", args)
        self.assertIn("--remove", args)
        self.assertIn("event24", args)
        self.assertIn("--bind", args)
        self.assertIn("/dev/input/js0", args)

    def test_initial_activation_is_non_destructive_and_silent(self):
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
        proc = SimpleNamespace(
            returncode=0,
            stdout="BOUND=event24\nBOUND=js0\n",
        )
        with (
            mock.patch.object(hotplug.SandboxBackend, "running", return_value=True),
            mock.patch.object(hotplug, "detect_host_gamepads", return_value=(device,)),
            mock.patch.object(hotplug, "attached_probe", side_effect=(probe, probe)),
            mock.patch.object(hotplug.Path, "is_file", return_value=True),
            mock.patch.object(hotplug.subprocess, "run", return_value=proc) as run,
        ):
            result = hotplug.reconcile_gamepads("Bottles", replace_existing=False)
        self.assertFalse(result.udev_notified)
        self.assertIn("udev=initial-static", result.format("iniziale"))
        args = run.call_args.args[0]
        self.assertNotIn("--notify", args)
        self.assertNotIn("--remove", args)
        self.assertIn("--bind", args)

    def test_udev_packet_has_libudev_header_and_exact_properties(self):
        packet = ns_helper._udev_packet(
            {
                "DEVPATH": "/devices/pci0000:00/input/input24/event24",
                "DEVNAME": "/dev/input/event24",
                "SUBSYSTEM": "input",
                "MAJOR": "13",
                "MINOR": "88",
            },
            "add",
        )
        header_format = "=8s8I"
        header_size = struct.calcsize(header_format)
        header = struct.unpack(header_format, packet[:header_size])
        self.assertEqual(b"libudev\0", header[0])
        self.assertEqual(
            ns_helper.UDEV_MONITOR_MAGIC,
            socket.ntohl(header[1]),
        )
        self.assertEqual(header_size, header[2])
        self.assertEqual(header_size, header[3])
        payload = packet[header_size:]
        self.assertIn(b"ACTION=add\0", payload)
        self.assertIn(b"DEVNAME=/dev/input/event24\0", payload)
        self.assertIn(b"SUBSYSTEM=input\0", payload)
        self.assertNotIn(b"hidraw", payload)

    def test_sysfs_root_validation_rejects_broad_or_outside_paths(self):
        with self.assertRaisesRegex(RuntimeError, "troppo ampia"):
            ns_helper._validate_sysfs_root(ns_helper.Path("/sys/devices"))
        with self.assertRaisesRegex(RuntimeError, "rifiutata"):
            ns_helper._validate_sysfs_root(ns_helper.Path("/sys/class/input"))

    def test_hotplug_helper_has_no_pid_namespace_dependency(self):
        self.assertFalse(hasattr(ns_helper, "CLONE_NEWPID"))
        self.assertTrue(hasattr(ns_helper, "OPEN_TREE_CLONE"))
        self.assertTrue(hasattr(ns_helper, "MOVE_MOUNT_F_EMPTY_PATH"))

    def test_fd_mount_api_uses_detached_mount_and_exact_target(self):
        open_tree = mock.Mock(return_value=77)
        move_mount = mock.Mock(return_value=0)
        with (
            mock.patch.object(ns_helper, "_open_tree_fn", open_tree),
            mock.patch.object(ns_helper, "_move_mount_fn", move_mount),
        ):
            mount_fd = ns_helper._open_tree_clone(9)
            ns_helper._move_mount_fd(mount_fd, ns_helper.Path("/dev/input/js0"))

        self.assertEqual(77, mount_fd)
        open_tree.assert_called_once_with(
            9,
            b"",
            ns_helper.AT_EMPTY_PATH
            | ns_helper.OPEN_TREE_CLONE
            | ns_helper.OPEN_TREE_CLOEXEC,
        )
        move_mount.assert_called_once_with(
            77,
            b"",
            ns_helper.AT_FDCWD,
            b"/dev/input/js0",
            ns_helper.MOVE_MOUNT_F_EMPTY_PATH,
        )

    def test_runtime_routes_through_mount_owner_entry_helper(self):
        self.assertEqual("gamepad_ns_entry.py", hotplug.NS_HELPER.name)

    def test_mount_namespace_owner_is_discovered_with_ns_get_userns(self):
        with mock.patch.object(ns_entry.fcntl, "ioctl", return_value=73) as ioctl:
            self.assertEqual(73, ns_entry._owning_userns(41))
        ioctl.assert_called_once_with(41, ns_entry.NS_GET_USERNS)

    def test_reopen_pinned_rejects_changed_device_identity(self):
        pinned = SimpleNamespace(
            st_dev=1, st_ino=2, st_mode=stat.S_IFCHR, st_rdev=3
        )
        changed = SimpleNamespace(
            st_dev=1, st_ino=9, st_mode=stat.S_IFCHR, st_rdev=3
        )
        with (
            mock.patch.object(ns_entry.os, "open", return_value=55),
            mock.patch.object(ns_entry.os, "fstat", side_effect=(changed, pinned)),
            mock.patch.object(ns_entry.os, "close") as close,
        ):
            with self.assertRaisesRegex(RuntimeError, "Risorsa host cambiata"):
                ns_entry._reopen_pinned(ns_entry.Path("/dev/input/js0"), 12)
        close.assert_called_once_with(55)


if __name__ == "__main__":
    unittest.main()
