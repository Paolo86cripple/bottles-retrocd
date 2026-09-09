#!/usr/bin/env python3
from __future__ import annotations

DISPLAY_AUTO = "auto"
DISPLAY_WAYLAND = "wayland"
DISPLAY_XWAYLAND = "xwayland"
DISPLAY_BACKENDS = (DISPLAY_AUTO, DISPLAY_WAYLAND, DISPLAY_XWAYLAND)

DISPLAY_LABELS = {
    DISPLAY_AUTO: "Auto",
    DISPLAY_WAYLAND: "Wayland nativo",
    DISPLAY_XWAYLAND: "XWayland",
}

PROTON_WAYLAND_VARIABLES = (
    "PROTON_ENABLE_WAYLAND",
    "PROTON_USE_WAYLAND",
)


def normalize_display_backend(value: object) -> str:
    """Return a supported display backend, failing safely to Auto."""
    if not isinstance(value, str):
        return DISPLAY_AUTO
    normalized = value.strip().casefold()
    return normalized if normalized in DISPLAY_BACKENDS else DISPLAY_AUTO


def proton_wayland_environment(backend: object) -> dict[str, str]:
    """Return environment values that must be set for native Proton Wayland."""
    selected = normalize_display_backend(backend)
    if selected != DISPLAY_WAYLAND:
        return {}
    return {name: "1" for name in PROTON_WAYLAND_VARIABLES}


def bubblewrap_display_args(backend: object) -> list[str]:
    """Encode the display policy as per-launch Bubblewrap environment arguments.

    XWayland removes both Proton Wayland opt-ins and ``WAYLAND_DISPLAY`` and
    forces GTK/Bottles itself onto its X11 backend. This is intentional: Bottles
    has a per-bottle experimental Wayland flag which can otherwise request
    native Wayland again after RetroCD starts it. No display socket or other
    sandbox permission is added here; the existing XWayland path must already
    be available in the Bubblejail profile.
    """
    selected = normalize_display_backend(backend)
    if selected == DISPLAY_AUTO:
        return []
    if selected == DISPLAY_XWAYLAND:
        args: list[str] = []
        for name in (*PROTON_WAYLAND_VARIABLES, "WAYLAND_DISPLAY"):
            args.extend(["--debug-bwrap-args", "unsetenv", name])
        args.extend(["--debug-bwrap-args", "setenv", "GDK_BACKEND", "x11"])
        return args

    args = []
    for name, value in proton_wayland_environment(selected).items():
        args.extend(["--debug-bwrap-args", "setenv", name, value])
    return args
