#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping


DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080


class DisplayBackend(str, Enum):
    XWAYLAND = "xwayland"
    WAYLAND = "wayland"
    GAMESCOPE_XWAYLAND = "gamescope-xwayland"


@dataclass(frozen=True, slots=True)
class DisplayDiagnostics:
    backend: DisplayBackend
    mit_shm_error: bool
    wayland_driver_seen: bool
    x11_driver_error_seen: bool
    gamescope_seen: bool
    gamescope_no_sys_nice: bool


def _validate_instance(instance: str) -> None:
    if not isinstance(instance, str) or not instance or "\x00" in instance:
        raise ValueError("Istanza Bubblejail non valida.")


def _validate_bottle(bottle: str) -> None:
    if not isinstance(bottle, str) or not bottle or "\x00" in bottle:
        raise ValueError("Nome bottle non valido.")


def gamescope_xwayland_wrapper(
    argv: Iterable[str],
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
) -> list[str]:
    """Wrap a command in the lightest supported nested Gamescope/XWayland path.

    The host DISPLAY is removed so Gamescope uses the Wayland backend. Gamescope
    then creates exactly one XWayland server inside the Bubblejail IPC namespace.
    Input and output are both 1:1 at 1920x1080 by default: no FSR/NIS, no frame
    limiter, no HDR, no adaptive-sync request, no MangoApp and no Steam mode.
    Color management is disabled to avoid work not needed by the SDR fallback.
    gamescopereaper keeps detached Wine descendants tied to the compositor
    lifecycle without shell sleeps or polling hacks.
    """
    if width <= 0 or height <= 0 or width > 16384 or height > 16384:
        raise ValueError("Risoluzione Gamescope non valida.")
    child = list(argv)
    if not child:
        raise ValueError("Comando Gamescope vuoto.")
    return [
        "env", "-u", "DISPLAY",
        "gamescope",
        "--backend", "wayland",
        "--xwayland-count", "1",
        "--disable-color-management",
        "-w", str(width), "-h", str(height),
        "-W", str(width), "-H", str(height),
        "-f",
        "--",
        "gamescopereaper", "--",
        *child,
    ]


def bottles_command(
    instance: str,
    argv: Iterable[str],
    *,
    backend: DisplayBackend,
    wait: bool = True,
) -> list[str]:
    """Build a Bubblejail command without weakening its namespace boundary."""
    _validate_instance(instance)
    command = ["bubblejail", "run"]
    if wait:
        command.append("--wait")
    command.append(instance)

    child = list(argv)
    if backend is DisplayBackend.WAYLAND:
        command += ["env", "-u", "DISPLAY", *child]
    elif backend is DisplayBackend.GAMESCOPE_XWAYLAND:
        command += gamescope_xwayland_wrapper(child)
    elif backend is DisplayBackend.XWAYLAND:
        command += child
    else:
        raise ValueError(f"Backend display non supportato: {backend!r}")
    return command


def bottles_tool_command(
    instance: str,
    bottle: str,
    tool: str,
    *,
    backend: DisplayBackend,
) -> list[str]:
    allowed = {"winecfg", "regedit", "taskmgr", "control", "explorer", "uninstaller", "cmd"}
    if tool not in allowed:
        raise ValueError(f"Tool Wine non ammesso nel probe display: {tool}")
    _validate_bottle(bottle)
    return bottles_command(
        instance,
        ["bottles-cli", "tools", "-b", bottle, tool],
        backend=backend,
    )


def bottles_executable_command(
    instance: str,
    bottle: str,
    executable: str,
    *,
    backend: DisplayBackend,
) -> list[str]:
    _validate_bottle(bottle)
    if not isinstance(executable, str) or not executable or "\x00" in executable:
        raise ValueError("Executable Windows non valido.")
    return bottles_command(
        instance,
        ["bottles-cli", "run", "-b", bottle, "-e", executable],
        backend=backend,
    )


def wayland_session_available(env: Mapping[str, str]) -> bool:
    return bool(env.get("WAYLAND_DISPLAY") and env.get("XDG_RUNTIME_DIR"))


def diagnose_output(output: str, *, backend: DisplayBackend) -> DisplayDiagnostics:
    text = output or ""
    mit_shm = "MIT-SHM" in text and (
        "X_ShmPutImage" in text
        or "BadValue" in text
        or "BadAccess" in text
        or "XShm" in text
    )
    return DisplayDiagnostics(
        backend=backend,
        mit_shm_error=mit_shm,
        wayland_driver_seen="waylanddrv:" in text,
        x11_driver_error_seen=("X Error of failed request" in text or "winex11" in text),
        gamescope_seen=("gamescope version" in text or "Starting Xwayland on" in text),
        gamescope_no_sys_nice="No CAP_SYS_NICE" in text,
    )
