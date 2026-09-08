#!/usr/bin/env python3
from __future__ import annotations

import os
import platform
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

CDEMU_DBUS_NAME = "net.sf.cdemu.CDEmuDaemon"
CDEMU_DBUS_PATH = "/Daemon"
CDEMU_DBUS_INTERFACE = "net.sf.cdemu.CDEmuDaemon"

REQUIRED_PACKAGES = ("cdemu-daemon", "libmirage")
OPTIONAL_PACKAGES = ("cdemu-client",)
VHBA_PROVIDERS = ("vhba-module-dkms", "vhba-module")
TRACKED_PACKAGES = REQUIRED_PACKAGES + OPTIONAL_PACKAGES + VHBA_PROVIDERS


@dataclass(frozen=True, slots=True)
class CommandResult:
    returncode: int
    stdout: str


@dataclass(frozen=True, slots=True)
class PackageState:
    name: str
    installed: bool
    version: str = ""
    pending_version: str = ""


@dataclass(frozen=True, slots=True)
class LifecycleReport:
    kernel: str
    packages: tuple[PackageState, ...]
    vhba_provider: str
    vhba_loaded: bool
    vhba_control_present: bool
    vhba_control_char: bool
    vhba_module_path: str
    kernel_headers_present: bool
    daemon_service_active: bool
    daemon_reachable: bool
    daemon_version: str
    libmirage_runtime_version: str
    interface_version: str
    device_count: int | None
    failures: tuple[str, ...]
    warnings: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.failures


Runner = Callable[[Sequence[str], float], CommandResult]


def run_command(args: Sequence[str], timeout: float = 8.0) -> CommandResult:
    try:
        proc = subprocess.run(
            list(args),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(127, str(exc))
    return CommandResult(proc.returncode, proc.stdout or "")


def _package_state(name: str, runner: Runner) -> PackageState:
    result = runner(("pacman", "-Q", name), 5.0)
    if result.returncode != 0:
        return PackageState(name=name, installed=False)
    line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
    parts = line.split(maxsplit=1)
    if len(parts) != 2 or parts[0] != name:
        return PackageState(name=name, installed=False)
    return PackageState(name=name, installed=True, version=parts[1])


def _pending_updates(runner: Runner) -> dict[str, str]:
    result = runner(("pacman", "-Qu"), 8.0)
    # pacman -Qu returns 0 when updates exist and 1 when none exist.
    if result.returncode not in {0, 1}:
        return {}
    updates: dict[str, str] = {}
    for line in result.stdout.splitlines():
        match = re.match(r"^(\S+)\s+\S+\s+->\s+(\S+)\s*$", line.strip())
        if match:
            updates[match.group(1)] = match.group(2)
    return updates


def _parse_single_string(text: str) -> str:
    # gdbus normally prints e.g. ('3.3.1',). Keep this deliberately narrow.
    match = re.search(r"\(['\"]([^'\"]+)['\"]\s*,?\)", text.strip())
    return match.group(1) if match else ""


def _parse_interface_version(text: str) -> str:
    values = re.findall(r"\b(\d+)\b", text)
    if len(values) < 2:
        return ""
    return f"{int(values[-2])}.{int(values[-1])}"


def _parse_device_count(text: str) -> int | None:
    values = re.findall(r"\b(\d+)\b", text)
    return int(values[-1]) if values else None


def _gdbus_call(runner: Runner, method: str, timeout: float = 5.0) -> CommandResult:
    return runner(
        (
            "gdbus",
            "call",
            "--session",
            "--dest",
            CDEMU_DBUS_NAME,
            "--object-path",
            CDEMU_DBUS_PATH,
            "--method",
            method,
        ),
        timeout,
    )


def inspect_lifecycle(
    *,
    runner: Runner = run_command,
    kernel: str | None = None,
    sys_root: Path = Path("/sys"),
    dev_root: Path = Path("/dev"),
    modules_root: Path = Path("/usr/lib/modules"),
) -> LifecycleReport:
    kernel = kernel or platform.release()
    updates = _pending_updates(runner)
    packages = []
    by_name: dict[str, PackageState] = {}
    for name in TRACKED_PACKAGES:
        state = _package_state(name, runner)
        if state.installed and name in updates:
            state = PackageState(name, True, state.version, updates[name])
        packages.append(state)
        by_name[name] = state

    if by_name["vhba-module-dkms"].installed:
        provider = "vhba-module-dkms"
    elif by_name["vhba-module"].installed:
        provider = "vhba-module"
    else:
        provider = ""

    vhba_loaded = (sys_root / "module" / "vhba").exists()
    vhba_ctl = dev_root / "vhba_ctl"
    vhba_control_present = vhba_ctl.exists()
    vhba_control_char = False
    if vhba_control_present:
        try:
            vhba_control_char = stat.S_ISCHR(vhba_ctl.stat().st_mode)
        except OSError:
            vhba_control_char = False

    modinfo = runner(("modinfo", "-n", "vhba"), 5.0)
    vhba_module_path = modinfo.stdout.strip().splitlines()[0] if modinfo.returncode == 0 and modinfo.stdout.strip() else ""
    kernel_headers_present = (modules_root / kernel / "build").exists()

    service = runner(("systemctl", "--user", "is-active", "cdemu-daemon.service"), 5.0)
    daemon_service_active = service.returncode == 0 and service.stdout.strip() == "active"

    ping = _gdbus_call(runner, "org.freedesktop.DBus.Peer.Ping")
    daemon_reachable = ping.returncode == 0
    daemon_version = ""
    library_version = ""
    interface_version = ""
    device_count: int | None = None
    if daemon_reachable:
        daemon = _gdbus_call(runner, f"{CDEMU_DBUS_INTERFACE}.GetDaemonVersion")
        library = _gdbus_call(runner, f"{CDEMU_DBUS_INTERFACE}.GetLibraryVersion")
        interface = _gdbus_call(runner, f"{CDEMU_DBUS_INTERFACE}.GetDaemonInterfaceVersion2")
        count = _gdbus_call(runner, f"{CDEMU_DBUS_INTERFACE}.GetNumberOfDevices")
        if daemon.returncode == 0:
            daemon_version = _parse_single_string(daemon.stdout)
        if library.returncode == 0:
            library_version = _parse_single_string(library.stdout)
        if interface.returncode == 0:
            interface_version = _parse_interface_version(interface.stdout)
        if count.returncode == 0:
            device_count = _parse_device_count(count.stdout)

    failures: list[str] = []
    warnings: list[str] = []

    for name in REQUIRED_PACKAGES:
        if not by_name[name].installed:
            failures.append(f"pacchetto richiesto non installato: {name}")

    if not provider:
        failures.append("nessun provider VHBA installato")
    elif "cachyos" in kernel.lower() and provider != "vhba-module-dkms":
        failures.append(
            f"kernel CachyOS {kernel} con provider {provider}: usare vhba-module-dkms"
        )

    if provider == "vhba-module-dkms" and not kernel_headers_present:
        failures.append(f"headers del kernel corrente assenti: {modules_root / kernel / 'build'}")
    if not vhba_module_path:
        failures.append("modinfo non trova il modulo vhba per il kernel corrente")
    elif kernel not in vhba_module_path:
        warnings.append(
            f"modulo vhba risolto fuori dalla directory del kernel corrente: {vhba_module_path}"
        )
    if not vhba_loaded:
        failures.append("modulo kernel vhba non caricato")
    if not vhba_control_present:
        failures.append("/dev/vhba_ctl assente sul host")
    elif not vhba_control_char:
        failures.append("/dev/vhba_ctl esiste ma non è un character device")
    if not daemon_reachable:
        failures.append("daemon CDEmu non raggiungibile sul D-Bus di sessione")
    if daemon_reachable and not daemon_version:
        failures.append("versione runtime cdemu-daemon non leggibile")
    if daemon_reachable and not library_version:
        failures.append("versione runtime libMirage non leggibile")
    if daemon_reachable and not interface_version:
        failures.append("versione interfaccia CDEmu non leggibile")
    elif interface_version and not interface_version.startswith("7."):
        failures.append(f"interfaccia CDEmu incompatibile: {interface_version} (attesa major 7)")

    daemon_pkg = by_name["cdemu-daemon"]
    lib_pkg = by_name["libmirage"]
    if daemon_pkg.installed and daemon_version and not daemon_pkg.version.startswith(daemon_version):
        warnings.append(
            f"versione daemon runtime {daemon_version} diversa dal pacchetto {daemon_pkg.version}"
        )
    if lib_pkg.installed and library_version and not lib_pkg.version.startswith(library_version):
        warnings.append(
            f"versione libMirage runtime {library_version} diversa dal pacchetto {lib_pkg.version}"
        )
    if not daemon_service_active and daemon_reachable:
        warnings.append("daemon raggiungibile via D-Bus ma systemd --user non lo riporta active")

    for state in packages:
        if state.pending_version:
            warnings.append(f"aggiornamento disponibile: {state.name} {state.version} -> {state.pending_version}")

    return LifecycleReport(
        kernel=kernel,
        packages=tuple(packages),
        vhba_provider=provider,
        vhba_loaded=vhba_loaded,
        vhba_control_present=vhba_control_present,
        vhba_control_char=vhba_control_char,
        vhba_module_path=vhba_module_path,
        kernel_headers_present=kernel_headers_present,
        daemon_service_active=daemon_service_active,
        daemon_reachable=daemon_reachable,
        daemon_version=daemon_version,
        libmirage_runtime_version=library_version,
        interface_version=interface_version,
        device_count=device_count,
        failures=tuple(failures),
        warnings=tuple(warnings),
    )


def update_command(report: LifecycleReport) -> tuple[str, ...]:
    """Return the explicit full-system Arch update command; never execute it."""
    packages = ["cdemu-daemon", "libmirage"]
    if report.vhba_provider == "vhba-module-dkms" or "cachyos" in report.kernel.lower():
        packages.append("vhba-module-dkms")
    elif report.vhba_provider:
        packages.append(report.vhba_provider)
    packages.append("cdemu-client")
    return ("sudo", "pacman", "-Syu", "--needed", *packages)


def format_report(report: LifecycleReport) -> str:
    lines = [
        f"[{'PASS' if report.ok else 'FAIL'}] Retro Optical lifecycle · kernel {report.kernel}",
        f"VHBA: provider={report.vhba_provider or 'assente'} · loaded={'sì' if report.vhba_loaded else 'no'} · "
        f"ctl={'char' if report.vhba_control_char else ('presente' if report.vhba_control_present else 'assente')}",
        f"Modulo: {report.vhba_module_path or 'non trovato'}",
        f"Headers kernel: {'presenti' if report.kernel_headers_present else 'assenti'}",
        f"CDEmu: D-Bus={'ok' if report.daemon_reachable else 'FAIL'} · systemd={'active' if report.daemon_service_active else 'inactive'} · "
        f"daemon={report.daemon_version or '—'} · libMirage={report.libmirage_runtime_version or '—'} · "
        f"API={report.interface_version or '—'} · device={report.device_count if report.device_count is not None else '—'}",
        "Pacchetti:",
    ]
    for state in report.packages:
        if state.installed:
            pending = f" -> {state.pending_version}" if state.pending_version else ""
            lines.append(f"  {'[UPD]' if pending else '[OK] '} {state.name} {state.version}{pending}")
        else:
            optional = " (opzionale)" if state.name in OPTIONAL_PACKAGES else ""
            lines.append(f"  [--]  {state.name}: non installato{optional}")
    lines.extend(f"[FAIL] {item}" for item in report.failures)
    lines.extend(f"[WARN] {item}" for item in report.warnings)
    lines.append("Aggiornamento consigliato (non eseguito): " + " ".join(update_command(report)))
    return "\n".join(lines)
