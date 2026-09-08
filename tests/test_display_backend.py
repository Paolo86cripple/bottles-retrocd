from __future__ import annotations

import unittest

from display_backend import (
    DEFAULT_HEIGHT,
    DEFAULT_WIDTH,
    DisplayBackend,
    bottles_executable_command,
    bottles_tool_command,
    diagnose_output,
    gamescope_xwayland_wrapper,
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

    def test_host_xwayland_preserves_existing_display_path(self):
        self.assertEqual(
            [
                "bubblejail", "run", "--wait", "Bottles",
                "bottles-cli", "tools", "-b", "Probe", "winecfg",
            ],
            bottles_tool_command(
                "Bottles", "Probe", "winecfg", backend=DisplayBackend.XWAYLAND
            ),
        )

    def test_gamescope_xwayland_is_lightweight_1080p_one_to_one(self):
        command = gamescope_xwayland_wrapper(["bottles-cli", "tools", "-b", "Probe", "winecfg"])
        self.assertEqual(["env", "-u", "DISPLAY"], command[:3])
        self.assertIn("gamescope", command)
        self.assertEqual("wayland", command[command.index("--backend") + 1])
        self.assertEqual("1", command[command.index("--xwayland-count") + 1])
        self.assertIn("--disable-color-management", command)
        self.assertEqual(str(DEFAULT_WIDTH), command[command.index("-w") + 1])
        self.assertEqual(str(DEFAULT_HEIGHT), command[command.index("-h") + 1])
        self.assertEqual(str(DEFAULT_WIDTH), command[command.index("-W") + 1])
        self.assertEqual(str(DEFAULT_HEIGHT), command[command.index("-H") + 1])
        self.assertIn("-f", command)
        for forbidden in (
            "--rt", "--adaptive-sync", "--immediate-flips", "--mangoapp",
            "--hdr-enabled", "-r", "-S", "-F", "-e",
        ):
            self.assertNotIn(forbidden, command)
        self.assertEqual(
            ["gamescopereaper", "--", "bottles-cli", "tools", "-b", "Probe", "winecfg"],
            command[command.index("gamescopereaper"):],
        )

    def test_gamescope_backend_is_inside_bubblejail(self):
        command = bottles_tool_command(
            "Bottles", "Probe", "winecfg", backend=DisplayBackend.GAMESCOPE_XWAYLAND
        )
        self.assertEqual(["bubblejail", "run", "--wait", "Bottles"], command[:4])
        self.assertEqual("gamescope", command[7])
        self.assertEqual("gamescopereaper", command[command.index("--", 8) + 1])

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

    def test_gamescope_capability_warning_is_diagnostic_only(self):
        diag = diagnose_output(
            "[gamescope] console: gamescope version 3.16.25\n"
            "No CAP_SYS_NICE, falling back to regular-priority compute and threads.\n"
            "[gamescope] wlserver: Starting Xwayland on :1\n",
            backend=DisplayBackend.GAMESCOPE_XWAYLAND,
        )
        self.assertTrue(diag.gamescope_seen)
        self.assertTrue(diag.gamescope_no_sys_nice)
        self.assertFalse(diag.mit_shm_error)

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
