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

from runtime_bus_audit import (  # noqa: E402
    bubblejail_runtime_bus_audit_invocation,
    format_runtime_bus_audit,
    parse_runtime_bus_audit_output,
)
from runtime_proxy_policy import format_proxy_policy, inspect_proxy_policy  # noqa: E402
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
            "Elenca in sola lettura D-Bus, socket UNIX, runtime, device e policy effettiva del proxy D-Bus "
            "della jail già avviata. Il test non modifica la policy Bubblejail."
        )
        self.runtime_audit_btn.connect(
            "clicked", lambda *_: self.background(self.run_runtime_surface_audit, report=True)
        )
        parent = self.test_disc_cache_btn.get_parent()
        if isinstance(parent, Gtk.Box):
            parent.append(self.runtime_audit_btn)
        else:
            raise RuntimeError("Layout Test inatteso: impossibile inserire Analizza runtime sandbox.")

    def launch_bottles(self):
        """Avoid self-contention between the short CDEmu operation lock and stale-state probe.

        The hardening layer serializes the complete non-live launch with the
        short operation flock. The preserved controller then calls
        ``_cleanup_inactive_live_session()``, whose stale-state probe needs the
        same lock through ``acquire_session_lock()``. Two independent opens of
        the same flock file can conflict even within one process. For a non-live
        launch, hold the already-supported session lease temporarily instead:
        nested ownership checks become re-entrant on the same store, while a
        genuinely separate RetroCD process is still excluded. No journal is
        created and the lease is always released when the launch path returns.
        Live multidisc keeps the original long-lived hardening path unchanged.
        """
        live_requested = bool(self.ui_get(self.live_multidisc_switch.get_active))
        if live_requested:
            return super().launch_bottles()

        if not self.cdemu_ownership.session_locked:
            self._recover_stale_cdemu_state()
        self.cdemu_ownership.acquire_session_lock(timeout=2.0)
        try:
            if self.cdemu_ownership.load() is not None:
                raise _hard.CDEmuOwnershipError(
                    "Journal CDEmu non risolto prima dell'avvio non-live; operazione rifiutata."
                )
            return super(_hard.Window, self).launch_bottles()
        finally:
            self.cdemu_ownership.release_session_lock()

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

        bus_proc = run_cmd(bubblejail_runtime_bus_audit_invocation(INSTANCE), timeout=20)
        if bus_proc.returncode != 0:
            raise RuntimeError(
                f"Audit D-Bus Bubblejail terminato con rc={bus_proc.returncode}:\n{bus_proc.stdout[-4000:]}"
            )
        bus_report = parse_runtime_bus_audit_output(bus_proc.stdout)

        # Host-side and read-only: inspect only the policy flags on the exact
        # xdg-dbus-proxy process serving this Bubblejail instance. This avoids
        # inferring broad permissions from one successful D-Bus method call.
        proxy_report = inspect_proxy_policy(INSTANCE, self.sandbox.config())

        return (
            format_runtime_audit(report)
            + "\n\n"
            + format_runtime_bus_audit(bus_report)
            + "\n\n"
            + format_proxy_policy(proxy_report)
        )

    def set_busy(self, busy: bool):
        super().set_busy(busy)
        button = getattr(self, "runtime_audit_btn", None)
        if button is not None:
            button.set_sensitive(not busy)


_hard._game._release_base.Window = Window
App = _hard.App

if __name__ == "__main__":
    raise SystemExit(App().run())
