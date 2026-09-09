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

# Bottles' official cpak manifest uses the GLib keyfile backend because a
# container should not depend on the host dconf writer. In Bubblejail this also
# gives us exactly the persistence boundary we want: the keyfile lives below
# the instance's private, persistent HOME instead of writing to the host dconf
# database. This covers global Bottles preferences such as dark-theme and temp.
BOTTLES_GSETTINGS_BACKEND = "keyfile"


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


def bottles_persistent_environment() -> dict[str, str]:
    """Environment required for isolated, persistent Bottles preferences."""
    return {"GSETTINGS_BACKEND": BOTTLES_GSETTINGS_BACKEND}


def bubblewrap_display_args(backend: object) -> list[str]:
    """Encode Bottles persistence and display policy as per-launch bwrap args.

    The GSettings keyfile backend is always selected so Bottles global
    preferences persist inside Bubblejail's private HOME without exposing the
    host dconf database.

    Auto otherwise leaves display selection untouched. Native Wayland enables
    the Proton-CachyOS Wayland aliases. XWayland removes those opt-ins and
    reports an X11 session to Bottles via ``XDG_SESSION_TYPE=x11``. We
    deliberately keep ``WAYLAND_DISPLAY`` and do not force ``GDK_BACKEND``:
    the Bottles GTK UI can therefore continue to use Wayland while Wine/Proton
    takes the X11/XWayland path. The Bubblejail ``x11`` service supplies the
    XWayland socket and clipboard surface; no new filesystem, device or network
    permission is added here.
    """
    selected = normalize_display_backend(backend)
    args: list[str] = []

    for name, value in bottles_persistent_environment().items():
        args.extend(["--debug-bwrap-args", "setenv", name, value])

    if selected == DISPLAY_AUTO:
        return args

    if selected == DISPLAY_XWAYLAND:
        for name in PROTON_WAYLAND_VARIABLES:
            args.extend(["--debug-bwrap-args", "unsetenv", name])
        args.extend([
            "--debug-bwrap-args", "setenv", "XDG_SESSION_TYPE", "x11",
        ])
        return args

    for name, value in proton_wayland_environment(selected).items():
        args.extend(["--debug-bwrap-args", "setenv", name, value])
    return args
