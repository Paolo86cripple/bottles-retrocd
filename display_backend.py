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
    """Encode display policy as per-launch Bubblewrap environment arguments.

    Auto leaves the process environment untouched. Native Wayland enables the
    Proton-CachyOS Wayland aliases. XWayland removes those opt-ins and reports an
    X11 session to Bottles via ``XDG_SESSION_TYPE=x11``. Bottles uses that value
    when deciding whether to apply its per-bottle experimental Wine Wayland
    preference, while GTK itself can still connect to the host Wayland display.

    No display socket, filesystem path, device or network permission is added.
    """
    selected = normalize_display_backend(backend)
    if selected == DISPLAY_AUTO:
        return []
    if selected == DISPLAY_XWAYLAND:
        args: list[str] = []
        for name in PROTON_WAYLAND_VARIABLES:
            args.extend(["--debug-bwrap-args", "unsetenv", name])
        args.extend([
            "--debug-bwrap-args", "setenv", "XDG_SESSION_TYPE", "x11",
        ])
        return args

    args = []
    for name, value in proton_wayland_environment(selected).items():
        args.extend(["--debug-bwrap-args", "setenv", name, value])
    return args
