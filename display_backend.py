#!/usr/bin/env python3
from __future__ import annotations

import os
import tomllib
from pathlib import Path

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


def required_bubblejail_display_services(backend: object) -> tuple[str, ...]:
    """Return the existing Bubblejail services required by a forced backend.

    XWayland intentionally keeps both services: ``x11`` supplies XWayland and
    its clipboard surface, while ``wayland`` lets the Bottles GTK UI stay on
    Wayland. This mirrors the safe display subset of Bottles' cpak manifest
    (displayX11 + socketWayland) without enabling network or broad devices.
    """
    selected = normalize_display_backend(backend)
    if selected == DISPLAY_WAYLAND:
        return ("wayland",)
    if selected == DISPLAY_XWAYLAND:
        return ("x11", "wayland")
    return ()


def validate_bubblejail_display_services(config: object, backend: object) -> None:
    """Fail closed when a forced display backend lacks its Bubblejail services."""
    if not isinstance(config, dict):
        raise RuntimeError("Profilo Bubblejail non valido: configurazione display illeggibile.")
    required = required_bubblejail_display_services(backend)
    missing = [service for service in required if service not in config]
    if missing:
        raise RuntimeError(
            "Backend display non disponibile nel profilo Bubblejail: mancano "
            + ", ".join(f"[{name}]" for name in missing)
            + ". RetroCD non aggiunge automaticamente nuovi permessi al profilo."
        )


def _bubblejail_services_path() -> Path:
    data_home = Path(
        os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
    ).expanduser()
    instance = os.environ.get("BOTTLES_RETRO_CD_INSTANCE", "Bottles")
    return data_home / "bubblejail" / "instances" / instance / "services.toml"


def ensure_bubblejail_display_services(backend: object) -> None:
    """Validate the real profile when it exists on the current target host.

    Unit tests and source-tree checks may run where no Bubblejail instance has
    been created yet; in that case there is nothing meaningful to validate.
    On an installed target, an existing instance directory with a missing or
    malformed services.toml is treated as a hard failure.
    """
    services_path = _bubblejail_services_path()
    instance_dir = services_path.parent
    if not instance_dir.exists():
        return
    if not services_path.is_file():
        raise RuntimeError(f"Profilo Bubblejail incompleto: manca {services_path}.")
    try:
        with services_path.open("rb") as stream:
            config = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"Impossibile validare {services_path}: {exc}") from exc
    validate_bubblejail_display_services(config, backend)


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
    ensure_bubblejail_display_services(selected)

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
