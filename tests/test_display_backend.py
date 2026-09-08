from __future__ import annotations

import unittest

from display_backend import (
    DisplayBackend,
    bottles_executable_command,
    bottles_tool_command,
    diagnose_output,
    wayland_session_available,
)


class DisplayBackendTests(unittest.TestCase):
    def test_wayland_tool_unsets_display_only_inside_child(self):
        self.assertEqual(
            [
                "bubblejail", "run", "--wait", "Bottles",
                "env", "-u", "DISPLAY",
                "bottles-cli", "tools", "-b", "Probe", "winecfg",
            ],
            bottles_tool_command(
                "Bottles", "Probe", "winecfg", backend=DisplayBackend.WAYLAND
            ),
        )

    def test_xwayland_tool_preserves_existing_display_path(self):
        self.assertEqual(
            [
                "bubblejail", "run", "--wait", "Bottles",
                "bottles-cli", "tools", "-b", "Probe", "winecfg",
            ],
            bottles_tool_command(
                "Bottles", "Probe", "winecfg", backend=DisplayBackend.XWAYLAND
            ),
        )

    def test_wayland_executable_uses_same_narrow_transport(self):
        command = bottles_executable_command(
            "Bottles",
            "Probe",
            "/tmp/Program Files/tool.exe",
            backend=DisplayBackend.WAYLAND,
        )
        self.assertEqual("env", command[4])
        self.assertEqual(["-u", "DISPLAY"], command[5:7])
        self.assertEqual("bottles-cli", command[7])
        self.assertEqual("/tmp/Program Files/tool.exe", command[-1])

    def test_mit_shm_failure_is_detected(self):
        diag = diagnose_output(
            "X Error of failed request: BadValue\n"
            "Major opcode 130 (MIT-SHM)\n"
            "Minor opcode 3 (X_ShmPutImage)\n",
            backend=DisplayBackend.XWAYLAND,
        )
        self.assertTrue(diag.mit_shm_error)
        self.assertTrue(diag.x11_driver_error_seen)
        self.assertFalse(diag.wayland_driver_seen)

    def test_wayland_driver_log_is_not_treated_as_failure(self):
        diag = diagnose_output(
            "00f0:err:waylanddrv:wayland_process_init optional protocol unavailable\n",
            backend=DisplayBackend.WAYLAND,
        )
        self.assertFalse(diag.mit_shm_error)
        self.assertTrue(diag.wayland_driver_seen)

    def test_wayland_session_requires_socket_and_runtime_dir(self):
        self.assertTrue(
            wayland_session_available(
                {"WAYLAND_DISPLAY": "wayland-0", "XDG_RUNTIME_DIR": "/run/user/1000"}
            )
        )
        self.assertFalse(wayland_session_available({"WAYLAND_DISPLAY": "wayland-0"}))

    def test_unknown_tool_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "non ammesso"):
            bottles_tool_command(
                "Bottles", "Probe", "not-a-tool", backend=DisplayBackend.WAYLAND
            )


if __name__ == "__main__":
    unittest.main()
