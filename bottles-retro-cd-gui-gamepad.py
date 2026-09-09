#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

LIFECYCLE_GUI = Path(__file__).with_name("bottles-retro-cd-gui-lifecycle.py")
_spec = importlib.util.spec_from_file_location("_bottles_retro_cd_lifecycle", LIFECYCLE_GUI)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Impossibile caricare la GUI RetroCD lifecycle: {LIFECYCLE_GUI}")
_life = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_life)

Gtk = _life.Gtk
GLib = _life.GLib

from gamepad_backend import GamepadBackend, detect_host_gamepads  # noqa: E402


class Window(_life.Window):
    """Final 0.4.0 wrapper adding narrow Bubblejail gamepad management."""

    def __init__(self, app):
        super().__init__(app)
        self.gamepad = GamepadBackend(_life._ext._base.INSTANCE)
        self._install_gamepad_controls()
        self.refresh_gamepad_status()

    def _install_gamepad_controls(self) -> None:
        frame = Gtk.Frame(label="Gamepad")
        box = self.frame_box(frame)

        self.gamepad_status = Gtk.Label(
            label="Gamepad: verifica in corso…",
            xalign=0,
            wrap=True,
            selectable=True,
        )
        box.append(self.gamepad_status)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(actions)
        self.gamepad_toggle_btn = Gtk.Button(label="Abilita gamepad")
        self.gamepad_toggle_btn.connect(
            "clicked", lambda *_: self.background(self.toggle_gamepad_service)
        )
        actions.append(self.gamepad_toggle_btn)

        self.gamepad_test_btn = Gtk.Button(label="Test gamepad")
        self.gamepad_test_btn.connect(
            "clicked", lambda *_: self.background(self.test_gamepad, report=True)
        )
        actions.append(self.gamepad_test_btn)

        note = Gtk.Label(
            label=(
                "Usa esclusivamente il servizio Bubblejail [joystick]: vengono esposti i nodi "
                "jsX del controller e i relativi eventX, non l'intero /dev/input. "
                "Nessun /dev/hidraw viene aggiunto da RetroCD. Collega il controller prima "
                "di avviare Bottles; hotplug/reconnect non è garantito nella 0.4.0."
            ),
            xalign=0,
            wrap=True,
        )
        note.add_css_class("dim-label")
        box.append(note)

        parent = self.launch_btn.get_parent()
        previous = self.launch_btn.get_prev_sibling()
        if isinstance(parent, Gtk.Box) and previous is not None:
            parent.insert_child_after(frame, previous)
        else:
            raise RuntimeError(
                "Layout Sandbox inatteso: impossibile inserire il supporto gamepad."
            )

    def refresh_gamepad_status(self):
        status = getattr(self, "gamepad_status", None)
        toggle = getattr(self, "gamepad_toggle_btn", None)
        if status is None or toggle is None:
            return False
        try:
            enabled = self.gamepad.enabled()
            devices = detect_host_gamepads()
            if devices:
                host = "; ".join(
                    f"{device.name} ({', '.join(Path(node).name for node in device.nodes)})"
                    for device in devices
                )
            else:
                host = "nessun controller jsX/evdev collegato"
            status.set_text(
                f"Bubblejail [joystick]: {'ON' if enabled else 'OFF'} · host: {host}"
            )
            toggle.set_label("Disabilita gamepad" if enabled else "Abilita gamepad")
        except Exception as exc:
            status.set_text(f"Gamepad: impossibile verificare il profilo: {exc}")
            toggle.set_label("Gestisci gamepad")
        return False

    def toggle_gamepad_service(self) -> str:
        enabled = self.gamepad.enabled()
        backup = self.gamepad.set_enabled(not enabled)
        state = "abilitato" if not enabled else "disabilitato"
        backup_text = f" Backup: {backup}." if backup is not None else ""
        return (
            f"Supporto gamepad Bubblejail {state} tramite [joystick]."
            + backup_text
            + " Nessun bind globale di /dev/input è stato aggiunto."
        )

    def test_gamepad(self) -> str:
        return self.gamepad.test()

    def launch_bottles(self):
        gamepad_enabled = self.gamepad.enabled()
        host_devices = detect_host_gamepads() if gamepad_enabled else ()
        result = super().launch_bottles()
        if not gamepad_enabled:
            return str(result) + " · gamepad OFF"
        if not host_devices:
            return str(result) + " · gamepad ON · nessun controller collegato all'avvio"
        names = ", ".join(device.name for device in host_devices)
        return str(result) + f" · gamepad ON ({names})"

    def refresh_all(self):
        result = super().refresh_all()
        self.refresh_gamepad_status()
        return result

    def set_busy(self, busy: bool):
        super().set_busy(busy)
        toggle = getattr(self, "gamepad_toggle_btn", None)
        test = getattr(self, "gamepad_test_btn", None)
        if toggle is not None:
            toggle.set_sensitive(not busy)
        if test is not None:
            test.set_sensitive(not busy)


# App.do_activate() resolves Window from the preserved base GUI module.
_life._ext._base.Window = Window
App = _life.App

if __name__ == "__main__":
    raise SystemExit(App().run())
