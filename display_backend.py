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


def normalize_display_backend(value: object) -> str:
    """Return a supported display backend, failing safely to Auto."""
    if not isinstance(value, str):
        return DISPLAY_AUTO
    normalized = value.strip().casefold()
    return normalized if normalized in DISPLAY_BACKENDS else DISPLAY_AUTO


def proton_wayland_environment(backend: object) -> dict[str, str]:
    """Return per-launch Proton/CachyOS Wayland controls for *backend*.

    Auto deliberately returns no overrides so Bottles and the selected runner
    retain their normal behaviour. Wayland and XWayland only alter runner
    display selection; they do not change Bubblejail sockets, filesystem,
    network, GPU or optical permissions.
    """
    selected = normalize_display_backend(backend)
    if selected == DISPLAY_AUTO:
        return {}
    enabled = "1" if selected == DISPLAY_WAYLAND else "0"
    return {
        "PROTON_ENABLE_WAYLAND": enabled,
        "PROTON_USE_WAYLAND": enabled,
    }


def bubblewrap_display_args(backend: object) -> list[str]:
    """Encode display overrides as Bubblewrap setenv runtime arguments."""
    args: list[str] = []
    for name, value in proton_wayland_environment(backend).items():
        args.extend(["--debug-bwrap-args", "setenv", name, value])
    return args
