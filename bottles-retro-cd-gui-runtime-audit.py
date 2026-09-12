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
from runtime_proxy_policy import (  # noqa: E402
    format_proxy_policy,
    inspect_proxy_policy,
    validate_profile_policy,
    validate_proxy_policy,
)
from runtime_sandbox_test_policy import normalize_sandbox_test_results  # noqa: E402
from runtime_surface_audit import (  # noqa: E402
    bubblejail_runtime_audit_invocation,
    format_runtime_audit,
    parse_runtime_audit_output,
)
from sandbox_backend import INSTANCE, run_cmd  # noqa: E402


class Window(_hard.Window):
    """Add validated runtime auditing without broadening the game policy."""

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

    def run_sandbox_test(self):
        """Keep the legacy self-test but apply the validated 0.4.1 dconf policy."""
        test_network = self.ui_get(self.test_network_check.get_active)
        results = normalize_sandbox_test_results(self.sandbox.test())
        if test_network:
            results += self.sandbox.test_runtime_network()
        lines = [f"[{state}] {name}: {detail}" for state, name, detail in results]
        passed = sum(1 for state, _, _ in results if state == "PASS")
        failed = sum(1 for state, _, _ in results if state == "FAIL")
        warned = sum(1 for state, _, _ in results if state == "WARN")
        lines.append(f"\nRisultato sandbox: PASS={passed} FAIL={failed} WARN={warned}")
        return "\n".join(lines)

    def launch_bottles(self):
        """Refuse launch if the static Bubblejail D-Bus profile can expose host dconf."""
        validate_profile_policy(self.sandbox.config())
        return super().launch_bottles()

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
        proxy_report = validate_proxy_policy(
            inspect_proxy_policy(INSTANCE, self.sandbox.config())
        )

        return (
            format_runtime_audit(report)
            + "\n\n"
            + format_runtime_bus_audit(bus_report)
            + "\n\n"
            + "[PASS] D-Bus host: proxy filtrato · dconf bloccato\n"
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
