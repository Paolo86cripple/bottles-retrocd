from __future__ import annotations

import unittest

from display_backend import (
    bubblewrap_display_args,
    normalize_display_backend,
    proton_wayland_environment,
)


class DisplayBackendTests(unittest.TestCase):
    def test_auto_adds_no_runtime_override(self):
        self.assertEqual("auto", normalize_display_backend("AUTO"))
        self.assertEqual({}, proton_wayland_environment("auto"))
        self.assertEqual([], bubblewrap_display_args("auto"))

    def test_wayland_sets_only_runner_display_environment(self):
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
                "--debug-bwrap-args", "setenv", "PROTON_ENABLE_WAYLAND", "1",
                "--debug-bwrap-args", "setenv", "PROTON_USE_WAYLAND", "1",
            ],
            args,
        )
        joined = " ".join(args)
        for forbidden in ("share-net", "ro-bind", "dev-bind", "/dev/dri", "/dev/sr", "/dev/sg"):
            self.assertNotIn(forbidden, joined)

    def test_xwayland_disables_native_proton_wayland(self):
        self.assertEqual(
            {
                "PROTON_ENABLE_WAYLAND": "0",
                "PROTON_USE_WAYLAND": "0",
            },
            proton_wayland_environment("xwayland"),
        )

    def test_unknown_value_fails_safely_to_auto(self):
        self.assertEqual("auto", normalize_display_backend(None))
        self.assertEqual("auto", normalize_display_backend("not-a-backend"))
        self.assertEqual([], bubblewrap_display_args("not-a-backend"))


if __name__ == "__main__":
    unittest.main()
