#!/usr/bin/env python3
"""0.4.1 diagnostic wrapper for effective Bubblejail runtime-surface auditing."""
from __future__ import annotations

import importlib.util
from pathlib import Path

HARDENING_GUI = Path(__file__).with_name("bottles-retro-cd-gui-hardening.py")
_spec = importlib.util.spec_from_file_location("_bottles_retro_cd_hardening", HARDENING_GUI)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Impossibile caricare la GUI RetroCD hardening: {HARDENING_GUI}")
_hard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hard)

Gtk = _hard.Gtk

from runtime_surface_audit import (  # noqa: E402
    bubblejail_runtime_audit_invocation,
    format_runtime_audit,
    parse_runtime_audit_output,
)
from sandbox_backend import INSTANCE, run_cmd  # noqa: E402


class Window(_hard.Window):
    """Add diagnostic runtime enumeration without changing the game policy."""

    def __init__(self, app):
        super().__init__(app)
        self._install_runtime_audit_button()

    def _install_runtime_audit_button(self) -> None:
        self.runtime_audit_btn = Gtk.Button(label="Analizza runtime sandbox")
        self.runtime_audit_btn.set_tooltip_text(
            "Elenca in sola lettura D-Bus, socket UNIX, runtime e device visibili nella jail già avviata. "
            "Il test non modifica la policy Bubblejail."
        )
        self.runtime_audit_btn.connect(
            "clicked", lambda *_: self.background(self.run_runtime_surface_audit, report=True)
        )
        parent = self.test_disc_cache_btn.get_parent()
        if isinstance(parent, Gtk.Box):
            parent.append(self.runtime_audit_btn)
        else:
            raise RuntimeError("Layout Test inatteso: impossibile inserire Analizza runtime sandbox.")

    def run_runtime_surface_audit(self) -> str:
        if not self.sandbox.running():
            raise RuntimeError(
                "Audit runtime disponibile solo con Bottles/Bubblejail già avviato tramite RetroCD."
            )
        proc = run_cmd(bubblejail_runtime_audit_invocation(INSTANCE), timeout=35)
        if proc.returncode != 0:
            raise RuntimeError(
                f"Audit runtime Bubblejail terminato con rc={proc.returncode}:\n{proc.stdout[-4000:]}"
            )
        report = parse_runtime_audit_output(proc.stdout)
        return format_runtime_audit(report)

    def set_busy(self, busy: bool):
        super().set_busy(busy)
        button = getattr(self, "runtime_audit_btn", None)
        if button is not None:
            button.set_sensitive(not busy)


# The original App.do_activate resolves Window through the preserved release-base
# module, so publish this outer wrapper there exactly like the prior layers.
_hard._game._release_base.Window = Window
App = _hard.App

if __name__ == "__main__":
    raise SystemExit(App().run())
