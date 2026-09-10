#!/usr/bin/env python3
"""Read-only D-Bus reachability diagnostics for the running Bottles jail.

This module complements runtime_surface_audit.py. It does not change Bubblejail
configuration and never invokes mutating application methods. The probe only
lists names through the already configured D-Bus proxies and sends a standard
org.freedesktop.DBus.Peer.Ping to ca.desrt.dconf to determine whether that
well-known name is merely visible or actually reachable through the proxy.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

BUS_AUDIT_SCHEMA = 1
BUS_AUDIT_PREFIX = "RETROCD_BUS_AUDIT_JSON="
MAX_ITEMS = 256
MAX_TEXT = 4096
_INSTANCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


@dataclass(frozen=True, slots=True)
class RuntimeBusReport:
    system_names: tuple[str, ...]
    system_unique_count: int
    dconf_reachable: bool
    dconf_detail: str
    warnings: tuple[str, ...]


def runtime_bus_probe_source() -> str:
    """Return the fixed stdlib-only read-only probe executed inside the jail."""
    return r'''import json
import os
import re
import subprocess

SCHEMA = 1
PREFIX = "RETROCD_BUS_AUDIT_JSON="
MAX_ITEMS = 256
MAX_TEXT = 4096
report = {
    "schema": SCHEMA,
    "system_names": [],
    "system_unique_count": 0,
    "dconf_reachable": False,
    "dconf_detail": "not-tested",
    "warnings": [],
}


def bounded_append(key, value):
    text = str(value)
    if len(text) > MAX_TEXT:
        text = text[:MAX_TEXT] + "…"
    if len(report[key]) < MAX_ITEMS:
        report[key].append(text)


def run_gdbus(args, label):
    try:
        return subprocess.run(
            ["gdbus", *args],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=4,
            check=False,
            env={**os.environ, "LC_ALL": "C"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        bounded_append("warnings", f"{label}: {type(exc).__name__}")
        return None


proc = run_gdbus([
    "call", "--system", "--dest", "org.freedesktop.DBus",
    "--object-path", "/org/freedesktop/DBus",
    "--method", "org.freedesktop.DBus.ListNames",
], "system ListNames")
if proc is not None:
    if proc.returncode != 0:
        bounded_append("warnings", f"system ListNames rc={proc.returncode}: {proc.stderr.strip()[:512]}")
    else:
        names = sorted(set(re.findall(r"'([^']+)'", proc.stdout)))
        report["system_unique_count"] = sum(1 for name in names if name.startswith(":"))
        for name in names:
            if not name.startswith(":"):
                bounded_append("system_names", name)

proc = run_gdbus([
    "call", "--session", "--dest", "ca.desrt.dconf",
    "--object-path", "/",
    "--method", "org.freedesktop.DBus.Peer.Ping",
], "dconf Peer.Ping")
if proc is not None:
    if proc.returncode == 0:
        report["dconf_reachable"] = True
        report["dconf_detail"] = "Peer.Ping riuscito"
    else:
        detail = proc.stderr.strip().replace("\n", " ")[:512]
        report["dconf_detail"] = f"Peer.Ping bloccato/non disponibile rc={proc.returncode}: {detail}"

report["system_names"] = sorted(set(report["system_names"]))
report["warnings"] = sorted(set(report["warnings"]))
print(PREFIX + json.dumps(report, ensure_ascii=True, sort_keys=True, separators=(",", ":")))
'''


def bubblejail_runtime_bus_audit_invocation(instance: str) -> list[str]:
    if not isinstance(instance, str) or _INSTANCE_RE.fullmatch(instance) is None:
        raise RuntimeError(f"Nome istanza Bubblejail non valido per audit D-Bus: {instance!r}")
    return [
        "/usr/bin/bubblejail",
        "run",
        "--wait",
        instance,
        "/usr/bin/python3",
        "-c",
        runtime_bus_probe_source(),
    ]


def _string_list(raw: object, key: str) -> tuple[str, ...]:
    if not isinstance(raw, list) or len(raw) > MAX_ITEMS:
        raise RuntimeError(f"Audit D-Bus: campo {key} non valido o oltre il limite.")
    result: list[str] = []
    for item in raw:
        if not isinstance(item, str) or len(item) > MAX_TEXT + 1:
            raise RuntimeError(f"Audit D-Bus: voce non valida in {key}.")
        result.append(item)
    return tuple(result)


def parse_runtime_bus_audit_output(text: str) -> RuntimeBusReport:
    if not isinstance(text, str) or len(text) > 1024 * 1024:
        raise RuntimeError("Audit D-Bus: output assente o eccessivamente grande.")
    payloads = [line[len(BUS_AUDIT_PREFIX):] for line in text.splitlines() if line.startswith(BUS_AUDIT_PREFIX)]
    if len(payloads) != 1:
        raise RuntimeError(f"Audit D-Bus: record JSON atteso=1, ottenuti={len(payloads)}.")
    try:
        raw = json.loads(payloads[0])
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Audit D-Bus: JSON non valido: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema") != BUS_AUDIT_SCHEMA:
        raise RuntimeError("Audit D-Bus: schema assente o incompatibile.")
    unique = raw.get("system_unique_count")
    reachable = raw.get("dconf_reachable")
    detail = raw.get("dconf_detail")
    if not isinstance(unique, int) or isinstance(unique, bool) or unique < 0:
        raise RuntimeError("Audit D-Bus: system_unique_count non valido.")
    if not isinstance(reachable, bool):
        raise RuntimeError("Audit D-Bus: dconf_reachable non valido.")
    if not isinstance(detail, str) or len(detail) > MAX_TEXT:
        raise RuntimeError("Audit D-Bus: dconf_detail non valido.")
    return RuntimeBusReport(
        system_names=_string_list(raw.get("system_names"), "system_names"),
        system_unique_count=unique,
        dconf_reachable=reachable,
        dconf_detail=detail,
        warnings=_string_list(raw.get("warnings"), "warnings"),
    )


def format_runtime_bus_audit(report: RuntimeBusReport) -> str:
    state = "raggiungibile" if report.dconf_reachable else "non raggiungibile"
    lines = [
        f"[INFO] D-Bus system: well-known={len(report.system_names)} unique={report.system_unique_count}",
        f"[INFO] ca.desrt.dconf: {state} · {report.dconf_detail}",
        "",
        f"[DBUS-SYSTEM] {len(report.system_names)}",
    ]
    lines.extend(f"  {name}" for name in report.system_names)
    if not report.system_names:
        lines.append("  —")
    if report.warnings:
        lines.append("")
        lines.append(f"[BUS-WARN] {len(report.warnings)}")
        lines.extend(f"  {item}" for item in report.warnings)
    return "\n".join(lines)


__all__ = [
    "BUS_AUDIT_PREFIX",
    "BUS_AUDIT_SCHEMA",
    "RuntimeBusReport",
    "bubblejail_runtime_bus_audit_invocation",
    "format_runtime_bus_audit",
    "parse_runtime_bus_audit_output",
    "runtime_bus_probe_source",
]
