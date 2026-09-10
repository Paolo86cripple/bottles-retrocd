#!/usr/bin/env python3
"""0.4.1 hardening wrapper: route archive parsing through verifier sandbox."""
from __future__ import annotations

import importlib.util
from pathlib import Path

GAMEPAD_GUI = Path(__file__).with_name("bottles-retro-cd-gui-gamepad.py")
_spec = importlib.util.spec_from_file_location("_bottles_retro_cd_gamepad", GAMEPAD_GUI)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Impossibile caricare la GUI RetroCD gamepad: {GAMEPAD_GUI}")
_game = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_game)

Gtk = _game.Gtk
GLib = _game.GLib

from verifier_sandbox import VerifierSandbox  # noqa: E402


class Window(_game.Window):
    """Keep the released game boundary unchanged; isolate verifier/scanner reads."""

    def __init__(self, app):
        super().__init__(app)
        self.verifier_sandbox = VerifierSandbox()
        self._install_verifier_sandbox_test()

    def _verifier_root(self) -> Path:
        root = getattr(self, "_archive_root", None)
        if not isinstance(root, Path) or not root.is_dir():
            raise RuntimeError("Configura prima una radice archivio RetroCD valida.")
        return root

    def _install_verifier_sandbox_test(self) -> None:
        self.verifier_sandbox_test_btn = Gtk.Button(label="Test sandbox verifica")
        self.verifier_sandbox_test_btn.set_tooltip_text(
            "Prova l'isolamento bwrap della verifica senza modificare i dump: archivio/codice/catalogo RO, "
            "sola cache di verifica RW, HOME host nascosta e rete host non condivisa."
        )
        self.verifier_sandbox_test_btn.connect(
            "clicked", lambda *_: self.background(self.test_verifier_sandbox, report=True)
        )
        parent = self.update_redump_btn.get_parent()
        if isinstance(parent, Gtk.Box):
            parent.append(self.verifier_sandbox_test_btn)
        else:
            raise RuntimeError("Layout Verifica inatteso: impossibile inserire Test sandbox verifica.")

    def test_verifier_sandbox(self) -> str:
        result = self.verifier_sandbox.attest(self._verifier_root())
        text = result.format()
        GLib.idle_add(self.verifier_result.set_text, text)
        return text

    def verify_selected_image(self):
        descriptor = self.selected_image()
        result = self.verifier_sandbox.verify(descriptor, self._verifier_root())
        GLib.idle_add(self.verifier_result.set_text, result.text)
        return result.text

    def verify_selected_set(self):
        descriptors = self.ui_get(
            lambda: tuple(entry.image for entry in self.disc_set.discs)
            if self.disc_set is not None and self.disc_set.discs else ()
        )
        if len(descriptors) < 2:
            raise RuntimeError("Il disco selezionato non appartiene a un set multidisco con almeno due supporti.")
        result = self.verifier_sandbox.verify_set(descriptors, self._verifier_root())
        GLib.idle_add(self.verifier_result.set_text, result.text)
        return result.text

    def scan_selected_image(self):
        descriptor = self.selected_image()
        result = self.verifier_sandbox.scan(descriptor, self._verifier_root())
        GLib.idle_add(self.verifier_result.set_text, result.text)
        return result.text

    def verify_and_scan_selected(self):
        descriptor = self.selected_image()
        result = self.verifier_sandbox.verify_scan(descriptor, self._verifier_root())
        GLib.idle_add(self.verifier_result.set_text, result.text)
        return result.text

    def set_busy(self, busy: bool):
        super().set_busy(busy)
        button = getattr(self, "verifier_sandbox_test_btn", None)
        if button is not None:
            button.set_sensitive(not busy)


# App.do_activate() resolves Window from the preserved release-base module.
_game._release_base.Window = Window
App = _game.App

if __name__ == "__main__":
    raise SystemExit(App().run())
