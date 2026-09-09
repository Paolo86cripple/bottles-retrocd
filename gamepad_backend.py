#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import shutil
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path

from sandbox_backend import INSTANCE, SandboxBackend, run_cmd

JOYSTICK_SERVICE = "joystick"
_SERVICE_RE = re.compile(
    r"(?ms)^\[joystick\][ \t]*(?:#.*)?\n.*?(?=^\[[^\n]+\][ \t]*(?:#.*)?$|\Z)"
)


@dataclass(frozen=True, slots=True)
class GamepadDevice:
    name: str
    js_node: str
    event_nodes: tuple[str, ...]

    @property
    def nodes(self) -> tuple[str, ...]:
        return (self.js_node, *self.event_nodes)


@dataclass(frozen=True, slots=True)
class GamepadProbe:
    input_dir_visible: bool
    nodes: dict[str, tuple[bool, bool]]
    hidraw_nodes: tuple[str, ...]


def _node_sort_key(name: str) -> tuple[str, int]:
    match = re.fullmatch(r"([A-Za-z_-]+)(\d+)", name)
    if match:
        return match.group(1), int(match.group(2))
    return name, -1


def _controller_name(sys_entry: Path, fallback: str) -> str:
    for candidate in (
        sys_entry / "device" / "name",
        sys_entry.resolve(strict=False).parent / "name",
    ):
        try:
            value = candidate.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if value:
            return value
    return fallback


def detect_host_gamepads(
    dev_input: Path = Path("/dev/input"),
    sys_class_input: Path = Path("/sys/class/input"),
) -> tuple[GamepadDevice, ...]:
    """Mirror Bubblejail's standard jsX -> eventX discovery, but only for jsX nodes."""
    if not dev_input.is_dir() or not sys_class_input.is_dir():
        return ()

    devices: list[GamepadDevice] = []
    for js_path in sorted(dev_input.glob("js*"), key=lambda p: _node_sort_key(p.name)):
        if re.fullmatch(r"js\d+", js_path.name) is None:
            continue
        try:
            st = js_path.stat()
        except OSError:
            continue
        if not stat.S_ISCHR(st.st_mode) or (st.st_mode & 0o004) == 0:
            continue

        sys_entry = sys_class_input / js_path.name
        try:
            resolved = sys_entry.resolve(strict=True)
            input_dir = resolved.parent
            entries = tuple(input_dir.iterdir())
        except OSError:
            continue

        event_nodes: list[str] = []
        for entry in entries:
            if re.fullmatch(r"event\d+", entry.name) is None:
                continue
            dev_node = dev_input / entry.name
            try:
                if stat.S_ISCHR(dev_node.stat().st_mode):
                    event_nodes.append(str(dev_node))
            except OSError:
                continue

        if not event_nodes:
            continue
        event_nodes.sort(key=lambda p: _node_sort_key(Path(p).name))
        devices.append(
            GamepadDevice(
                name=_controller_name(sys_entry, js_path.name),
                js_node=str(js_path),
                event_nodes=tuple(event_nodes),
            )
        )
    return tuple(devices)


def gamepad_probe_script() -> str:
    return r"""
set +e
if [ -d /dev/input ]; then
    printf 'GP_INPUT_DIR=1\n'
else
    printf 'GP_INPUT_DIR=0\n'
fi
for p in /dev/input/*; do
    [ -c "$p" ] || continue
    readable=0
    writable=0
    [ -r "$p" ] && readable=1
    [ -w "$p" ] && writable=1
    printf 'GP_NODE=%s|%s|%s\n' "${p##*/}" "$readable" "$writable"
done
for p in /dev/hidraw*; do
    [ -c "$p" ] || continue
    printf 'GP_HIDRAW=%s\n' "$p"
done
exit 0
""".lstrip()


def parse_gamepad_probe(output: str) -> GamepadProbe:
    input_dir_visible = False
    nodes: dict[str, tuple[bool, bool]] = {}
    hidraw: list[str] = []
    for line in output.splitlines():
        if line == "GP_INPUT_DIR=1":
            input_dir_visible = True
        elif line.startswith("GP_NODE="):
            payload = line.removeprefix("GP_NODE=")
            parts = payload.split("|")
            if len(parts) != 3 or not parts[0]:
                continue
            nodes[parts[0]] = (parts[1] == "1", parts[2] == "1")
        elif line.startswith("GP_HIDRAW="):
            value = line.removeprefix("GP_HIDRAW=").strip()
            if value:
                hidraw.append(value)
    return GamepadProbe(
        input_dir_visible=input_dir_visible,
        nodes=nodes,
        hidraw_nodes=tuple(sorted(set(hidraw))),
    )


class GamepadBackend:
    """Manage and verify Bubblejail's built-in [joystick] profile service."""

    def __init__(self, instance: str = INSTANCE, services_path: Path | None = None):
        self.instance = instance
        self.sandbox = SandboxBackend(instance)
        self.services_path = Path(services_path) if services_path is not None else self.sandbox.services_path
        self.backup_path = self.services_path.with_name(
            self.services_path.name + ".bottles-retro-cd.gamepad.bak"
        )

    def config(self) -> dict:
        try:
            with self.services_path.open("rb") as stream:
                raw = tomllib.load(stream)
        except OSError as exc:
            raise RuntimeError(f"Impossibile leggere {self.services_path}: {exc}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise RuntimeError(f"services.toml non valido: {exc}") from exc
        if not isinstance(raw, dict):
            raise RuntimeError("services.toml non contiene una configurazione valida.")
        return raw

    def enabled(self) -> bool:
        return JOYSTICK_SERVICE in self.config()

    def _running(self) -> bool:
        return self.sandbox.running()

    def set_enabled(self, enabled: bool) -> Path | None:
        if self._running():
            raise RuntimeError(
                "Chiudi Bottles/Bubblejail prima di modificare il supporto gamepad."
            )
        try:
            text = self.services_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise RuntimeError(f"Impossibile leggere {self.services_path}: {exc}") from exc

        try:
            parsed = tomllib.loads(text)
        except tomllib.TOMLDecodeError as exc:
            raise RuntimeError(f"services.toml non valido: {exc}") from exc

        currently_enabled = JOYSTICK_SERVICE in parsed
        if currently_enabled == bool(enabled):
            return None

        if enabled:
            updated = text.rstrip() + "\n\n[joystick]\n"
        else:
            updated = _SERVICE_RE.sub("", text).rstrip() + "\n"

        try:
            check = tomllib.loads(updated)
        except tomllib.TOMLDecodeError as exc:
            raise RuntimeError(
                f"La modifica gamepad produrrebbe TOML non valido: {exc}"
            ) from exc
        if (JOYSTICK_SERVICE in check) != bool(enabled):
            raise RuntimeError("Verifica post-modifica [joystick] fallita.")

        shutil.copy2(self.services_path, self.backup_path)
        tmp = self.services_path.with_name(self.services_path.name + ".gamepad.tmp")
        try:
            tmp.write_text(updated, encoding="utf-8")
            os.chmod(tmp, self.services_path.stat().st_mode & 0o777)
            os.replace(tmp, self.services_path)
            self.config()
        finally:
            tmp.unlink(missing_ok=True)
        return self.backup_path

    def test(self) -> str:
        if self._running():
            raise RuntimeError(
                "Chiudi Bottles/Bubblejail prima del Test gamepad."
            )
        if not self.enabled():
            raise RuntimeError(
                "Il servizio Bubblejail [joystick] è disattivato. Abilitalo prima del test."
            )

        host_devices = detect_host_gamepads()
        if not host_devices:
            raise RuntimeError(
                "Nessun gamepad standard jsX/evdev rilevato sull'host. "
                "Collega il controller prima di avviare il test."
            )

        expected = {
            Path(node).name
            for device in host_devices
            for node in device.nodes
        }
        proc = run_cmd(
            ["bubblejail", "run", "--debug-shell", self.instance],
            input_text=gamepad_probe_script(),
            timeout=40,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"Probe gamepad Bubblejail fallita (rc={proc.returncode}).\n"
                + proc.stdout[-3000:]
            )

        probe = parse_gamepad_probe(proc.stdout)
        if not probe.input_dir_visible:
            raise RuntimeError("/dev/input non è disponibile nella jail con [joystick] attivo.")

        actual = set(probe.nodes)
        missing = sorted(expected - actual, key=_node_sort_key)
        unexpected = sorted(actual - expected, key=_node_sort_key)
        unreadable = sorted(
            (name for name in expected if name in probe.nodes and not probe.nodes[name][0]),
            key=_node_sort_key,
        )

        failures: list[str] = []
        if missing:
            failures.append("nodi attesi mancanti: " + ", ".join(missing))
        if unexpected:
            failures.append(
                "nodi /dev/input non appartenenti ai gamepad rilevati: "
                + ", ".join(unexpected)
            )
        if unreadable:
            failures.append("nodi gamepad non leggibili: " + ", ".join(unreadable))
        if probe.hidraw_nodes:
            failures.append(
                "hidraw esposto senza necessità: " + ", ".join(probe.hidraw_nodes)
            )
        if failures:
            raise RuntimeError(
                "Isolamento gamepad non conforme: "
                + "; ".join(failures)
                + "\nOutput probe:\n"
                + proc.stdout[-3000:]
            )

        writable = sorted(
            (name for name in expected if probe.nodes.get(name, (False, False))[1]),
            key=_node_sort_key,
        )
        device_lines = [
            f"[INFO] {device.name}: "
            + ", ".join(Path(node).name for node in device.nodes)
            for device in host_devices
        ]
        return "\n".join(
            [
                "[PASS] Bubblejail [joystick] attivo",
                *device_lines,
                "[PASS] soli nodi gamepad attesi visibili: "
                + ", ".join(sorted(expected, key=_node_sort_key)),
                "[PASS] tutti i nodi gamepad attesi sono leggibili",
                "[PASS] /dev/hidraw* non esposto",
                "[INFO] nodi scrivibili (force-feedback se supportato): "
                + (", ".join(writable) if writable else "nessuno"),
                "[INFO] collega il controller prima di avviare Bottles; "
                "hotplug/reconnect non è garantito nella 0.4.0",
            ]
        )
