#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping


class DisplayBackend(str, Enum):
    XWAYLAND = "xwayland"
    WAYLAND = "wayland"


@dataclass(frozen=True, slots=True)
class DisplayDiagnostics:
    backend: DisplayBackend
    mit_shm_error: bool
    wayland_driver_seen: bool
    x11_driver_error_seen: bool


def bottles_command(
    instance: str,
    argv: Iterable[str],
    *,
    backend: DisplayBackend,
    wait: bool = True,
) -> list[str]:
    """Build a Bubblejail command without weakening the sandbox.

    Native Wayland is selected narrowly by removing DISPLAY from the child
    environment.  WAYLAND_DISPLAY and the Bubblejail Wayland service remain
    untouched.  XWayland keeps the inherited DISPLAY exactly as before.
    """
    if not isinstance(instance, str) or not instance or "\x00" in instance:
        raise ValueError("Istanza Bubblejail non valida.")
    command = ["bubblejail", "run"]
    if wait:
        command.append("--wait")
    command.append(instance)
    if backend is DisplayBackend.WAYLAND:
        command += ["env", "-u", "DISPLAY"]
    elif backend is not DisplayBackend.XWAYLAND:
        raise ValueError(f"Backend display non supportato: {backend!r}")
    command += list(argv)
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
    if not isinstance(bottle, str) or not bottle or "\x00" in bottle:
        raise ValueError("Nome bottle non valido.")
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
    if not isinstance(bottle, str) or not bottle or "\x00" in bottle:
        raise ValueError("Nome bottle non valido.")
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
    )
