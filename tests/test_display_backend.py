from __future__ import annotations

import unittest

from display_backend import (
    bottles_persistent_environment,
    bubblewrap_display_args,
    normalize_display_backend,
    proton_wayland_environment,
    required_bubblejail_display_services,
    validate_bubblejail_display_services,
)


class DisplayBackendTests(unittest.TestCase):
    def test_persistent_environment_uses_keyfile_backend(self):
        self.assertEqual(
            {"GSETTINGS_BACKEND": "keyfile"},
            bottles_persistent_environment(),
        )

    def test_cpak_style_display_service_requirements(self):
        self.assertEqual((), required_bubblejail_display_services("auto"))
        self.assertEqual(("wayland",), required_bubblejail_display_services("wayland"))
        self.assertEqual(("x11", "wayland"), required_bubblejail_display_services("xwayland"))

        validate_bubblejail_display_services({"wayland": {}}, "wayland")
        validate_bubblejail_display_services({"x11": {}, "wayland": {}}, "xwayland")

        with self.assertRaisesRegex(RuntimeError, r"\[wayland\]"):
            validate_bubblejail_display_services({"x11": {}}, "xwayland")
        with self.assertRaisesRegex(RuntimeError, r"\[x11\]"):
            validate_bubblejail_display_services({"wayland": {}}, "xwayland")
        with self.assertRaisesRegex(RuntimeError, "configurazione display illeggibile"):
            validate_bubblejail_display_services(None, "wayland")

    def test_auto_only_adds_isolated_preferences_backend(self):
        self.assertEqual("auto", normalize_display_backend("AUTO"))
        self.assertEqual({}, proton_wayland_environment("auto"))
        self.assertEqual(
            ["--debug-bwrap-args", "setenv", "GSETTINGS_BACKEND", "keyfile"],
            bubblewrap_display_args("auto"),
        )

    def test_wayland_sets_preferences_and_runner_display_environment(self):
        self.assertEqual(
            {
                "PROTON_ENABLE_WAYLAND": "1",
                "PROTON_USE_WAYLAND": "1",
            },
            proton_wayland_environment("wayland"),
        )
        args = bubblewrap_display_args("wayland")
        self.assertEqual(
            [
                "--debug-bwrap-args", "setenv", "GSETTINGS_BACKEND", "keyfile",
                "--debug-bwrap-args", "setenv", "PROTON_ENABLE_WAYLAND", "1",
                "--debug-bwrap-args", "setenv", "PROTON_USE_WAYLAND", "1",
            ],
            args,
        )
        joined = " ".join(args)
        for forbidden in ("share-net", "ro-bind", "dev-bind", "/dev/dri", "/dev/sr", "/dev/sg"):
            self.assertNotIn(forbidden, joined)

    def test_xwayland_keeps_bottles_gui_wayland_and_wine_on_x11(self):
        self.assertEqual({}, proton_wayland_environment("xwayland"))
        args = bubblewrap_display_args("xwayland")
        self.assertEqual(
            [
                "--debug-bwrap-args", "setenv", "GSETTINGS_BACKEND", "keyfile",
                "--debug-bwrap-args", "unsetenv", "PROTON_ENABLE_WAYLAND",
                "--debug-bwrap-args", "unsetenv", "PROTON_USE_WAYLAND",
                "--debug-bwrap-args", "setenv", "XDG_SESSION_TYPE", "x11",
            ],
            args,
        )
        joined = " ".join(args)
        self.assertNotIn("WAYLAND_DISPLAY", joined)
        self.assertNotIn("GDK_BACKEND", joined)
        for forbidden in ("share-net", "ro-bind", "dev-bind", "/dev/dri", "/dev/sr", "/dev/sg"):
            self.assertNotIn(forbidden, joined)

    def test_unknown_value_fails_safely_to_auto_display_policy(self):
        self.assertEqual("auto", normalize_display_backend(None))
        self.assertEqual("auto", normalize_display_backend("not-a-backend"))
        self.assertEqual(
            ["--debug-bwrap-args", "setenv", "GSETTINGS_BACKEND", "keyfile"],
            bubblewrap_display_args("not-a-backend"),
        )


if __name__ == "__main__":
    unittest.main()
