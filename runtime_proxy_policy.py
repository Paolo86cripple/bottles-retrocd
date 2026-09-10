#!/usr/bin/env python3
"""Read-only host audit of the active Bubblejail session D-Bus proxy policy."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MAX_ITEMS = 256
MAX_TEXT = 2048
_POLICY_PREFIXES = (
    "--filter",
    "--sloppy-names",
    "--see=",
    "--talk=",
    "--own=",
    "--call=",
    "--broadcast=",
)


@dataclass(frozen=True, slots=True)
class ProxyPolicyReport:
    portal_dconf_dbus: bool
    raw_session_args: tuple[str, ...]
    proxy_pids: tuple[int, ...]
    active_policy_args: tuple[str, ...]
    dconf_policy_args: tuple[str, ...]
    warnings: tuple[str, ...]


def _bounded_text(value: object) -> str:
    text = str(value)
    if len(text) > MAX_TEXT:
        return text[:MAX_TEXT] + "…"
    return text


def _string_list(value: object, *, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise RuntimeError(f"{label}: atteso array di stringhe.")
    if len(value) > MAX_ITEMS:
        raise RuntimeError(f"{label}: troppe voci ({len(value)}).")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise RuntimeError(f"{label}: voce non-stringa.")
        result.append(_bounded_text(item))
    return tuple(result)


def profile_dbus_policy(config: dict) -> tuple[bool, tuple[str, ...]]:
    portal = config.get("xdg_desktop_portal") or {}
    debug = config.get("debug") or {}
    if not isinstance(portal, dict) or not isinstance(debug, dict):
        raise RuntimeError("Profilo Bubblejail: sezione D-Bus non valida.")
    dconf = portal.get("dconf_dbus", False)
    if not isinstance(dconf, bool):
        raise RuntimeError("Profilo Bubblejail: xdg_desktop_portal.dconf_dbus non booleano.")
    raw = _string_list(debug.get("raw_dbus_session_args", []), label="debug.raw_dbus_session_args")
    return dconf, raw


def _policy_args(argv: tuple[str, ...]) -> tuple[str, ...]:
    result: list[str] = []
    for arg in argv:
        if arg in ("--filter", "--sloppy-names") or any(
            arg.startswith(prefix) for prefix in _POLICY_PREFIXES if prefix.endswith("=")
        ):
            if len(result) < MAX_ITEMS:
                result.append(_bounded_text(arg))
    return tuple(result)


def _name_pattern_matches(pattern: str, name: str) -> bool:
    if pattern == name:
        return True
    if pattern.endswith(".*"):
        base = pattern[:-2]
        return name == base or name.startswith(base + ".")
    return False


def _dconf_policy_args(args: tuple[str, ...]) -> tuple[str, ...]:
    target = "ca.desrt.dconf"
    matched: list[str] = []
    for arg in args:
        for kind in ("--talk=", "--own=", "--call="):
            if not arg.startswith(kind):
                continue
            rest = arg[len(kind):]
            pattern = rest.split("=", 1)[0] if kind == "--call=" else rest
            if _name_pattern_matches(pattern, target):
                matched.append(arg)
            break
    return tuple(matched)


def inspect_proxy_policy(instance: str, config: dict, *, proc_root: Path = Path("/proc")) -> ProxyPolicyReport:
    if not instance or "/" in instance or "\x00" in instance:
        raise RuntimeError(f"Nome istanza Bubblejail non valido: {instance!r}")
    portal_dconf, raw = profile_dbus_policy(config)
    uid = os.getuid()
    target_socket = f"/run/user/{uid}/bubblejail/{instance}/dbus_session_proxy"
    proxy_pids: list[int] = []
    policy: list[str] = []
    warnings: list[str] = []

    try:
        entries = list(proc_root.iterdir())
    except OSError as exc:
        raise RuntimeError(f"Impossibile enumerare {proc_root}: {exc}") from exc

    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            raw_cmd = (entry / "cmdline").read_bytes()
        except (OSError, PermissionError):
            continue
        if not raw_cmd:
            continue
        argv = tuple(
            chunk.decode("utf-8", "replace")
            for chunk in raw_cmd.split(b"\x00")
            if chunk
        )
        if not argv or Path(argv[0]).name != "xdg-dbus-proxy" or target_socket not in argv:
            continue
        proxy_pids.append(int(entry.name))
        for arg in _policy_args(argv):
            if arg not in policy and len(policy) < MAX_ITEMS:
                policy.append(arg)

    if not proxy_pids:
        warnings.append("proxy sessione Bubblejail non trovato in /proc")
    elif len(proxy_pids) > 1:
        warnings.append(f"proxy sessione Bubblejail ambiguo: {len(proxy_pids)} processi")

    active = tuple(policy)
    return ProxyPolicyReport(
        portal_dconf_dbus=portal_dconf,
        raw_session_args=raw,
        proxy_pids=tuple(sorted(proxy_pids)),
        active_policy_args=active,
        dconf_policy_args=_dconf_policy_args(active),
        warnings=tuple(warnings),
    )


def format_proxy_policy(report: ProxyPolicyReport) -> str:
    lines = [
        "[HOST-PROFILE] xdg_desktop_portal.dconf_dbus="
        + ("true" if report.portal_dconf_dbus else "false"),
        f"[HOST-PROFILE] debug.raw_dbus_session_args={len(report.raw_session_args)}",
    ]
    lines.extend(f"  {arg}" for arg in report.raw_session_args)
    lines.append(
        "[HOST-PROXY] pid="
        + (",".join(str(pid) for pid in report.proxy_pids) if report.proxy_pids else "—")
    )
    lines.append(f"[HOST-PROXY-POLICY] {len(report.active_policy_args)}")
    lines.extend(f"  {arg}" for arg in report.active_policy_args)
    if not report.active_policy_args:
        lines.append("  —")
    lines.append(f"[HOST-PROXY-DCONF] {len(report.dconf_policy_args)}")
    lines.extend(f"  {arg}" for arg in report.dconf_policy_args)
    if not report.dconf_policy_args:
        lines.append("  —")
    if report.warnings:
        lines.append(f"[HOST-PROXY-WARN] {len(report.warnings)}")
        lines.extend(f"  {item}" for item in report.warnings)
    return "\n".join(lines)


__all__ = [
    "ProxyPolicyReport",
    "format_proxy_policy",
    "inspect_proxy_policy",
    "profile_dbus_policy",
]
