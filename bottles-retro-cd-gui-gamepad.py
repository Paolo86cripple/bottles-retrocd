#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import tempfile
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
from gamepad_hotplug import GamepadHotplugMonitor  # noqa: E402


class Window(_life.Window):
    """Final 0.4.1 wrapper adding narrow Bubblejail gamepad management."""

    def __init__(self, app):
        super().__init__(app)
        self.gamepad = GamepadBackend(_life._ext._base.INSTANCE)
        self._gamepad_hotplug: GamepadHotplugMonitor | None = None
        self._install_gamepad_controls()
        self._enable_sandbox_scroll()
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

        self.gamepad_hotplug_status = Gtk.Label(
            label="Hotplug: in attesa del prossimo avvio Bottles",
            xalign=0,
            wrap=True,
            selectable=True,
        )
        self.gamepad_hotplug_status.add_css_class("dim-label")
        box.append(self.gamepad_hotplug_status)

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
                "Usa il servizio Bubblejail [joystick] e, dopo il lancio, un broker host-side che "
                "entra soltanto nei namespace necessari della stessa istanza per riconciliare i jsX/eventX "
                "dei gamepad realmente presenti. /dev/input non viene condiviso globalmente e /dev/hidraw "
                "resta escluso. Disconnect, reconnect e collegamento a Bottles già aperto vengono verificati "
                "dall'interno della jail dopo ogni cambio."
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

    def _enable_sandbox_scroll(self) -> None:
        sandbox_page = self.launch_btn.get_parent()
        if not isinstance(sandbox_page, Gtk.Box):
            raise RuntimeError("Layout Sandbox inatteso: pagina non riconosciuta per lo scroll.")

        current = self.notebook.get_current_page()
        sandbox_scroller = None

        # GtkNotebook's toplevel minimum can be constrained by any tall page,
        # even when Sandbox itself is scrollable. Wrap every final release page
        # so the window can genuinely shrink and each page scrolls vertically.
        for page_num in range(self.notebook.get_n_pages() - 1, -1, -1):
            page = self.notebook.get_nth_page(page_num)
            if page is None:
                continue
            if isinstance(page, Gtk.ScrolledWindow):
                page.set_min_content_height(0)
                page.set_propagate_natural_height(False)
                if page.get_child() is sandbox_page:
                    sandbox_scroller = page
                continue

            label = self.notebook.get_tab_label_text(page) or ""
            self.notebook.remove_page(page_num)

            scroll = Gtk.ScrolledWindow()
            scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
            scroll.set_hexpand(True)
            scroll.set_vexpand(True)
            scroll.set_min_content_height(0)
            scroll.set_propagate_natural_height(False)
            scroll.set_child(page)
            self.notebook.insert_page(scroll, Gtk.Label(label=label), page_num)

            if page is sandbox_page:
                sandbox_scroller = scroll

        if current >= 0:
            self.notebook.set_current_page(current)
        if sandbox_scroller is None:
            raise RuntimeError("Pagina Sandbox non trovata nel notebook dopo lo scroll globale.")
        self.sandbox_scroller = sandbox_scroller

    @staticmethod
    def _integration_sentinel_labels(text: str) -> str:
        return (
            text.replace("Data/progetti nascosta", "sentinel host integrazione #1 nascosta")
            .replace("Data/SteamLibrary nascosta", "sentinel host integrazione #2 nascosta")
        )

    def run_integration_test(self):
        """Run the reviewed CD test against real, temporary non-whitelist paths.

        The preserved base test already checks two DATA_ROOT children from inside
        the same Bubblejail invocation used for optical injection. Point those
        checks at a freshly-created sibling of the configured archive so a PASS
        proves that real host objects are hidden rather than merely proving that
        hard-coded paths happen not to exist.
        """
        base = _life._ext._base
        original_data_root = base.DATA_ROOT
        archive_parent = self._archive_root.parent

        try:
            with tempfile.TemporaryDirectory(
                prefix=".bottles-retro-integration-",
                dir=archive_parent,
            ) as temp_dir:
                sentinel_root = Path(temp_dir)
                (sentinel_root / "progetti").mkdir()
                (sentinel_root / "SteamLibrary").mkdir()
                base.DATA_ROOT = sentinel_root
                try:
                    result = super().run_integration_test()
                except RuntimeError as exc:
                    raise RuntimeError(
                        self._integration_sentinel_labels(str(exc))
                    ) from exc
                return self._integration_sentinel_labels(str(result))
        except OSError as exc:
            raise RuntimeError(
                f"Impossibile creare le sentinel host temporanee per il test CD → Bubblejail: {exc}"
            ) from exc
        finally:
            base.DATA_ROOT = original_data_root

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

    def _hotplug_callback(self, text: str, error: bool) -> None:
        GLib.idle_add(self._apply_hotplug_report, text, error)

    def _apply_hotplug_report(self, text: str, error: bool):
        status = getattr(self, "gamepad_hotplug_status", None)
        if status is not None:
            status.set_text(text)
        self.append_log(text)
        if error:
            self.set_message(text, True)
        return False

    def _start_hotplug_monitor(self) -> None:
        old = self._gamepad_hotplug
        if old is not None:
            old.stop()
        monitor = GamepadHotplugMonitor(
            _life._ext._base.INSTANCE,
            callback=self._hotplug_callback,
        )
        self._gamepad_hotplug = monitor
        monitor.start()
        GLib.idle_add(
            self.gamepad_hotplug_status.set_text,
            "Hotplug: broker exact-node avviato; in corso la prova sul mount namespace…",
        )

    def launch_bottles(self):
        gamepad_enabled = self.gamepad.enabled()
        host_devices = detect_host_gamepads() if gamepad_enabled else ()
        result = super().launch_bottles()
        if not gamepad_enabled:
            return str(result) + " · gamepad OFF"
        self._start_hotplug_monitor()
        if not host_devices:
            return str(result) + " · gamepad ON · hotplug attivo, nessun controller collegato all'avvio"
        names = ", ".join(device.name for device in host_devices)
        return str(result) + f" · gamepad ON ({names}) · hotplug attivo"

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
_release_base = _life._ext._base
_release_base.APP_ID = "io.github.Paolo86cripple.BottlesRetroCD"
_release_base.APP_NAME = "Bottles RetroCD"
_release_base.VERSION = "0.4.1"
_release_base.Window = Window
App = _life.App

if __name__ == "__main__":
    raise SystemExit(App().run())
