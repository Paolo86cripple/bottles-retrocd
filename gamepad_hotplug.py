#!/usr/bin/env python3
from __future__ import annotations

import os
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gamepad_backend import (
    GamepadDevice,
    detect_host_gamepads,
    gamepad_probe_script,
    parse_gamepad_probe,
)
from sandbox_backend import INSTANCE, SandboxBackend, run_cmd

NS_HELPER = Path(__file__).with_name("gamepad_ns_helper.py")


@dataclass(frozen=True, slots=True)
class HotplugResult:
    devices: tuple[GamepadDevice, ...]
    nodes: tuple[str, ...]
    writable_nodes: tuple[str, ...]

    def format(self, reason: str) -> str:
        names = ", ".join(device.name for device in self.devices) if self.devices else "nessun controller"
        nodes = ", ".join(self.nodes) if self.nodes else "nessuno"
        writable = ", ".join(self.writable_nodes) if self.writable_nodes else "nessuno"
        return (
            f"[PASS] Gamepad hotplug {reason}: {names} · nodi={nodes} · "
            f"scrivibili={writable} · hidraw=hidden"
        )


def _node_sort_key(name: str) -> tuple[str, int]:
    prefix = name.rstrip("0123456789")
    suffix = name[len(prefix):]
    return prefix, int(suffix) if suffix.isdecimal() else -1


def device_node_map(devices: tuple[GamepadDevice, ...]) -> dict[str, str]:
    result: dict[str, str] = {}
    for device in devices:
        for raw in device.nodes:
            path = Path(raw)
            if path.parent != Path("/dev/input"):
                raise RuntimeError(f"Nodo gamepad fuori da /dev/input: {path}")
            previous = result.setdefault(path.name, str(path))
            if previous != str(path):
                raise RuntimeError(f"Nodo gamepad ambiguo: {path.name}")
    return result


def host_fingerprint(devices: tuple[GamepadDevice, ...] | None = None) -> tuple[tuple[str, int, int], ...]:
    devices = detect_host_gamepads() if devices is None else devices
    entries: list[tuple[str, int, int]] = []
    for path in device_node_map(devices).values():
        try:
            st = os.stat(path)
            entries.append((path, int(st.st_ino), int(st.st_rdev)))
        except OSError:
            entries.append((path, -1, -1))
    return tuple(sorted(entries))


def attached_probe(instance: str = INSTANCE):
    proc = run_cmd(
        [
            "bubblejail",
            "run",
            "--wait",
            instance,
            "/bin/sh",
            "-c",
            gamepad_probe_script(),
        ],
        timeout=15,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Probe gamepad sull'istanza attiva fallita (rc={proc.returncode}).\n{proc.stdout[-3000:]}"
        )
    return parse_gamepad_probe(proc.stdout)


def validate_exact_probe(expected: set[str], probe) -> tuple[str, ...]:
    if not probe.input_dir_visible:
        raise RuntimeError("/dev/input non disponibile nella jail durante hotplug.")
    actual = set(probe.nodes)
    missing = sorted(expected - actual, key=_node_sort_key)
    unexpected = sorted(actual - expected, key=_node_sort_key)
    unreadable = sorted(
        (name for name in expected if name in probe.nodes and not probe.nodes[name][0]),
        key=_node_sort_key,
    )
    failures: list[str] = []
    if missing:
        failures.append("mancanti=" + ",".join(missing))
    if unexpected:
        failures.append("estranei=" + ",".join(unexpected))
    if unreadable:
        failures.append("non-leggibili=" + ",".join(unreadable))
    if probe.hidraw_nodes:
        failures.append("hidraw=" + ",".join(probe.hidraw_nodes))
    if failures:
        raise RuntimeError("Gamepad hotplug: isolamento non conforme: " + "; ".join(failures))
    return tuple(
        sorted(
            (name for name in expected if probe.nodes.get(name, (False, False))[1]),
            key=_node_sort_key,
        )
    )


def reconcile_gamepads(instance: str = INSTANCE, *, replace_existing: bool = True) -> HotplugResult:
    sandbox = SandboxBackend(instance)
    if not sandbox.running():
        raise RuntimeError("Bubblejail non è attiva; impossibile riconciliare il gamepad.")
    devices = detect_host_gamepads()
    expected_map = device_node_map(devices)
    expected = set(expected_map)

    before = attached_probe(instance)
    current = set(before.nodes)
    if before.hidraw_nodes:
        raise RuntimeError(
            "Gamepad hotplug rifiutato: /dev/hidraw* è già visibile nella jail: "
            + ", ".join(before.hidraw_nodes)
        )

    if not replace_existing and current != expected:
        raise RuntimeError(
            "Attivazione hotplug iniziale rifiutata: la superficie statica non coincide con i gamepad host "
            f"(jail={sorted(current)}, host={sorted(expected)})."
        )

    if not NS_HELPER.is_file():
        raise RuntimeError(f"Helper hotplug mancante: {NS_HELPER}")

    # First activation is non-destructive: overlay the exact host nodes on the
    # already validated static Bubblejail surface. Only after that succeeds do
    # later add/remove/reconnect events rebuild the current node set.
    command = [sys.executable, str(NS_HELPER), "--instance", instance]
    if replace_existing:
        for name in sorted(current, key=_node_sort_key):
            command += ["--remove", name]
    for name in sorted(expected, key=_node_sort_key):
        command += ["--bind", expected_map[name]]

    # Even an empty controller set invokes the helper: entering the exact
    # namespace and creating /dev/input makes a later first plug possible.
    proc = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=12,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Helper mount-namespace gamepad fallito (rc={proc.returncode}).\n{proc.stdout[-3000:]}"
        )

    after = attached_probe(instance)
    writable = validate_exact_probe(expected, after)
    return HotplugResult(
        devices=devices,
        nodes=tuple(sorted(expected, key=_node_sort_key)),
        writable_nodes=writable,
    )


class GamepadHotplugMonitor:
    """Poll only host gamepad identity and reconcile exact nodes on changes."""

    def __init__(
        self,
        instance: str = INSTANCE,
        callback: Callable[[str, bool], None] | None = None,
        interval: float = 0.5,
    ):
        self.instance = instance
        self.callback = callback
        self.interval = max(0.2, float(interval))
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _report(self, text: str, error: bool = False) -> None:
        if self.callback is not None:
            self.callback(text, error)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop,
            name="retrocd-gamepad-hotplug",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        sandbox = SandboxBackend(self.instance)
        previous: tuple[tuple[str, int, int], ...] | None = None
        activated = False
        first = True
        while not self._stop.is_set():
            if not sandbox.running():
                return
            try:
                devices = detect_host_gamepads()
                fingerprint = host_fingerprint(devices)
                if first or fingerprint != previous:
                    reason = "iniziale" if first else "evento add/remove/reconnect"
                    result = reconcile_gamepads(
                        self.instance,
                        replace_existing=activated,
                    )
                    self._report(result.format(reason), False)
                    previous = host_fingerprint()
                    activated = True
                    first = False
            except Exception as exc:
                self._report(f"[FAIL] Gamepad hotplug: {exc}", True)
                # On an initial capability failure no validated static node is
                # removed. A later physical device change gets another attempt.
                previous = host_fingerprint()
                first = False
            self._stop.wait(self.interval)
