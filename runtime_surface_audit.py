#!/usr/bin/env python3
"""Read-only diagnostics for the effective Bottles/Bubblejail runtime surface.

This module deliberately does not change Bubblejail policy.  It attaches a
short-lived Python probe to an already-running instance and records the actual
D-Bus names, runtime-directory entries, UNIX sockets, network interfaces and
security-sensitive device nodes visible from inside the jail.  Results are
bounded and serialized as JSON so diagnostic evidence cannot be forged by
newline-bearing filesystem names.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

AUDIT_SCHEMA = 1
AUDIT_PREFIX = "RETROCD_RUNTIME_AUDIT_JSON="
MAX_ITEMS = 256
MAX_TEXT = 4096
_INSTANCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True, slots=True)
class RuntimeSurfaceReport:
    uid: int
    xdg_runtime_dir: str
    display: str
    wayland_display: str
    dbus_address: str
    dbus_names: tuple[str, ...]
    dbus_unique_count: int
    runtime_entries: tuple[str, ...]
    filesystem_sockets: tuple[str, ...]
    proc_unix_names: tuple[str, ...]
    network_interfaces: tuple[str, ...]
    network_routes: tuple[str, ...]
    devices: tuple[str, ...]
    truncated: tuple[str, ...]
    warnings: tuple[str, ...]


def runtime_surface_probe_source() -> str:
    """Return the fixed stdlib-only probe executed inside the running jail."""
    # Keep this source self-contained.  The application itself requires Python,
    # while gdbus/ip are optional enrichments and are handled without failing the
    # whole diagnostic when unavailable.
    return r'''import glob
import json
import os
import pathlib
import re
import stat
import subprocess

SCHEMA = 1
PREFIX = "RETROCD_RUNTIME_AUDIT_JSON="
MAX_ITEMS = 256
MAX_TEXT = 4096

report = {
    "schema": SCHEMA,
    "uid": os.getuid(),
    "xdg_runtime_dir": os.environ.get("XDG_RUNTIME_DIR", "")[:MAX_TEXT],
    "display": os.environ.get("DISPLAY", "")[:MAX_TEXT],
    "wayland_display": os.environ.get("WAYLAND_DISPLAY", "")[:MAX_TEXT],
    "dbus_address": os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")[:MAX_TEXT],
    "dbus_names": [],
    "dbus_unique_count": 0,
    "runtime_entries": [],
    "filesystem_sockets": [],
    "proc_unix_names": [],
    "network_interfaces": [],
    "network_routes": [],
    "devices": [],
    "truncated": [],
    "warnings": [],
}


def bounded_append(key, value):
    text = str(value)
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + "…"
        if key not in report["truncated"]:
            report["truncated"].append(key)
    bucket = report[key]
    if len(bucket) >= MAX_ITEMS:
        if key not in report["truncated"]:
            report["truncated"].append(key)
        return False
    bucket.append(text)
    return True


def kind_for_mode(mode):
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISDIR(mode):
        return "dir"
    if stat.S_ISREG(mode):
        return "file"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISCHR(mode):
        return "char"
    if stat.S_ISBLK(mode):
        return "block"
    if stat.S_ISFIFO(mode):
        return "fifo"
    return "other"


def walk_bounded(root_text, max_depth):
    root = pathlib.Path(root_text)
    if not root.is_dir():
        return
    pending = [(root, 0)]
    while pending:
        parent, depth = pending.pop(0)
        try:
            entries = sorted(os.scandir(parent), key=lambda item: item.name)
        except OSError as exc:
            bounded_append("warnings", f"scandir {parent}: {type(exc).__name__}")
            continue
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError as exc:
                bounded_append("warnings", f"stat {entry.path}: {type(exc).__name__}")
                continue
            kind = kind_for_mode(info.st_mode)
            record = f"{kind} {entry.path}"
            bounded_append("runtime_entries", record)
            if kind == "socket":
                bounded_append("filesystem_sockets", entry.path)
            if depth < max_depth and kind == "dir":
                pending.append((pathlib.Path(entry.path), depth + 1))
            if len(report["runtime_entries"]) >= MAX_ITEMS:
                if "runtime_entries" not in report["truncated"]:
                    report["truncated"].append("runtime_entries")
                return


runtime_root = report["xdg_runtime_dir"]
if runtime_root:
    walk_bounded(runtime_root, 1)
for extra_root in ("/tmp/.X11-unix", "/tmp/.ICE-unix", "/tmp/.font-unix"):
    if pathlib.Path(extra_root).is_dir():
        try:
            for entry in sorted(os.scandir(extra_root), key=lambda item: item.name):
                try:
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if stat.S_ISSOCK(info.st_mode):
                    bounded_append("filesystem_sockets", entry.path)
        except OSError as exc:
            bounded_append("warnings", f"scandir {extra_root}: {type(exc).__name__}")

# List the names visible through the proxied session bus.  D-Bus names cannot
# contain quotes/newlines, so extracting quoted GVariant strings is sufficient
# and avoids importing a host D-Bus Python binding into the jail.
try:
    proc = subprocess.run(
        ["gdbus", "call", "--session", "--dest", "org.freedesktop.DBus",
         "--object-path", "/org/freedesktop/DBus", "--method", "org.freedesktop.DBus.ListNames"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=4,
        check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
except (OSError, subprocess.TimeoutExpired) as exc:
    bounded_append("warnings", f"gdbus ListNames: {type(exc).__name__}")
else:
    if proc.returncode != 0:
        bounded_append("warnings", f"gdbus ListNames rc={proc.returncode}: {proc.stderr.strip()[:512]}")
    else:
        names = sorted(set(re.findall(r"'([^']+)'", proc.stdout)))
        report["dbus_unique_count"] = sum(1 for name in names if name.startswith(":"))
        for name in names:
            if not name.startswith(":"):
                bounded_append("dbus_names", name)
        if len(names) > MAX_ITEMS:
            report["truncated"].append("dbus_names")

try:
    lines = pathlib.Path("/proc/net/unix").read_text(encoding="utf-8", errors="replace").splitlines()[1:]
except OSError as exc:
    bounded_append("warnings", f"/proc/net/unix: {type(exc).__name__}")
else:
    names = []
    for line in lines:
        fields = line.split()
        if len(fields) >= 8:
            names.append(fields[7])
    for name in sorted(set(names)):
        bounded_append("proc_unix_names", name)

try:
    proc = subprocess.run(
        ["ip", "-o", "link", "show"], text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=4, check=False, env={**os.environ, "LC_ALL": "C"},
    )
except (OSError, subprocess.TimeoutExpired) as exc:
    bounded_append("warnings", f"ip link: {type(exc).__name__}")
else:
    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            parts = line.split(": ", 2)
            if len(parts) >= 2:
                bounded_append("network_interfaces", parts[1].split("@", 1)[0])
    else:
        bounded_append("warnings", f"ip link rc={proc.returncode}")

try:
    proc = subprocess.run(
        ["ip", "-o", "route", "show"], text=True, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, timeout=4, check=False, env={**os.environ, "LC_ALL": "C"},
    )
except (OSError, subprocess.TimeoutExpired) as exc:
    bounded_append("warnings", f"ip route: {type(exc).__name__}")
else:
    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            bounded_append("network_routes", line)
    else:
        bounded_append("warnings", f"ip route rc={proc.returncode}")

patterns = (
    "/dev/dri/*",
    "/dev/input/*",
    "/dev/hidraw*",
    "/dev/sr*",
    "/dev/sg*",
    "/dev/snd/*",
    "/dev/video*",
    "/dev/media*",
    "/dev/bus/usb/*/*",
    "/dev/vhba_ctl",
    "/dev/kvm",
    "/dev/uinput",
    "/dev/net/tun",
    "/dev/fuse",
)
seen = set()
for pattern in patterns:
    for raw in glob.glob(pattern):
        if raw in seen:
            continue
        seen.add(raw)
        try:
            info = os.stat(raw, follow_symlinks=False)
        except OSError:
            continue
        kind = kind_for_mode(info.st_mode)
        suffix = ""
        if kind in {"char", "block"}:
            try:
                suffix = f" {os.major(info.st_rdev)}:{os.minor(info.st_rdev)}"
            except (TypeError, ValueError, OSError):
                suffix = ""
        bounded_append("devices", f"{kind} {raw}{suffix}")

for key in ("dbus_names", "runtime_entries", "filesystem_sockets", "proc_unix_names",
            "network_interfaces", "network_routes", "devices", "truncated", "warnings"):
    report[key] = sorted(set(report[key]))

print(PREFIX + json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
'''


def bubblejail_runtime_audit_invocation(instance: str) -> list[str]:
    """Attach the diagnostic probe to an already-running Bubblejail instance."""
    if not isinstance(instance, str) or _INSTANCE_RE.fullmatch(instance) is None:
        raise RuntimeError(f"Nome istanza Bubblejail non valido per audit runtime: {instance!r}")
    return [
        "/usr/bin/bubblejail",
        "run",
        "--wait",
        instance,
        "/usr/bin/python3",
        "-c",
        runtime_surface_probe_source(),
    ]


def _string_list(raw: object, key: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or len(raw) > MAX_ITEMS:
        raise RuntimeError(f"Audit runtime: campo {key} non valido o oltre il limite.")
    values: list[str] = []
    for item in raw:
        if not isinstance(item, str) or len(item) > MAX_TEXT + 1:
            raise RuntimeError(f"Audit runtime: voce non valida in {key}.")
        values.append(item)
    return tuple(values)


def parse_runtime_audit_output(text: str) -> RuntimeSurfaceReport:
    """Parse exactly one bounded JSON evidence record from Bubblejail output."""
    if not isinstance(text, str) or len(text) > 2 * 1024 * 1024:
        raise RuntimeError("Audit runtime: output assente o eccessivamente grande.")
    payloads = [line[len(AUDIT_PREFIX):] for line in text.splitlines() if line.startswith(AUDIT_PREFIX)]
    if len(payloads) != 1:
        raise RuntimeError(f"Audit runtime: record JSON atteso=1, ottenuti={len(payloads)}.")
    try:
        raw = json.loads(payloads[0])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Audit runtime: JSON non valido: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != AUDIT_SCHEMA:
        raise RuntimeError("Audit runtime: schema assente o incompatibile.")
    uid = raw.get("uid")
    unique_count = raw.get("dbus_unique_count")
    if not isinstance(uid, int) or isinstance(uid, bool) or uid < 0:
        raise RuntimeError("Audit runtime: uid non valido.")
    if not isinstance(unique_count, int) or isinstance(unique_count, bool) or unique_count < 0:
        raise RuntimeError("Audit runtime: dbus_unique_count non valido.")

    scalar: dict[str, str] = {}
    for key in ("xdg_runtime_dir", "display", "wayland_display", "dbus_address"):
        value = raw.get(key)
        if not isinstance(value, str) or len(value) > MAX_TEXT:
            raise RuntimeError(f"Audit runtime: campo {key} non valido.")
        scalar[key] = value

    return RuntimeSurfaceReport(
        uid=uid,
        xdg_runtime_dir=scalar["xdg_runtime_dir"],
        display=scalar["display"],
        wayland_display=scalar["wayland_display"],
        dbus_address=scalar["dbus_address"],
        dbus_names=_string_list(raw.get("dbus_names"), "dbus_names"),
        dbus_unique_count=unique_count,
        runtime_entries=_string_list(raw.get("runtime_entries"), "runtime_entries"),
        filesystem_sockets=_string_list(raw.get("filesystem_sockets"), "filesystem_sockets"),
        proc_unix_names=_string_list(raw.get("proc_unix_names"), "proc_unix_names"),
        network_interfaces=_string_list(raw.get("network_interfaces"), "network_interfaces"),
        network_routes=_string_list(raw.get("network_routes"), "network_routes"),
        devices=_string_list(raw.get("devices"), "devices"),
        truncated=_string_list(raw.get("truncated"), "truncated"),
        warnings=_string_list(raw.get("warnings"), "warnings"),
    )


def format_runtime_audit(report: RuntimeSurfaceReport) -> str:
    """Human-readable diagnostic report; intentionally no policy verdict yet."""
    lines = [
        "[INFO] Audit runtime sandbox: diagnostico read-only; nessuna policy modificata.",
        f"[INFO] uid={report.uid} XDG_RUNTIME_DIR={report.xdg_runtime_dir or '—'}",
        f"[INFO] display={report.display or '—'} wayland={report.wayland_display or '—'}",
        f"[INFO] rete: interfacce={list(report.network_interfaces) or ['—']} route={len(report.network_routes)}",
        f"[INFO] D-Bus: well-known={len(report.dbus_names)} unique={report.dbus_unique_count}",
    ]

    def section(title: str, values: tuple[str, ...]) -> None:
        lines.append(f"\n[{title}] {len(values)}")
        if values:
            lines.extend(f"  {item}" for item in values)
        else:
            lines.append("  —")

    section("DBUS", report.dbus_names)
    section("SOCKET-FS", report.filesystem_sockets)
    section("UNIX", report.proc_unix_names)
    section("RUNTIME", report.runtime_entries)
    section("DEVICE", report.devices)
    if report.network_routes:
        section("ROUTE", report.network_routes)
    if report.truncated:
        section("TRUNCATED", report.truncated)
    if report.warnings:
        section("WARN", report.warnings)
    return "\n".join(lines)


__all__ = [
    "AUDIT_PREFIX",
    "AUDIT_SCHEMA",
    "RuntimeSurfaceReport",
    "bubblejail_runtime_audit_invocation",
    "format_runtime_audit",
    "parse_runtime_audit_output",
    "runtime_surface_probe_source",
]
