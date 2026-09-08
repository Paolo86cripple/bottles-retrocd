#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

DGVOODOO_GUI = Path(__file__).with_name("bottles-retro-cd-gui-dgvoodoo.py")
_spec = importlib.util.spec_from_file_location("_bottles_retro_cd_dgvoodoo", DGVOODOO_GUI)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Impossibile caricare la GUI dgVoodoo2 RetroCD: {DGVOODOO_GUI}")
_dg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dg)

Gtk = _dg.Gtk
GLib = _dg.GLib

from dgvoodoo_probe import clean_probe, probe_executable, probe_status  # noqa: E402


class Window(_dg.Window):
    """Final GUI composition layer for Point 7."""

    def __init__(self, app):
        self._dg_cpl_process: subprocess.Popen[str] | None = None
        self._dg_cpl_log: Path | None = None
        super().__init__(app)
        self._install_explicit_dgvoodoo_controls()
        self._make_dgvoodoo_tab_scrollable()
        self._update_dg_action_sensitivity()

    def _install_explicit_dgvoodoo_controls(self) -> None:
        """Expose unambiguous state/probe actions in the Point-7 page."""
        self.dg_status_btn.set_label("Verifica stato")

        tool_row = self.dg_copy_override_btn.get_parent()
        if not isinstance(tool_row, Gtk.Box):
            raise RuntimeError("Riga strumenti dgVoodoo2 non trovata.")

        self.dg_probe_clean_btn = Gtk.Button(label="Pulisci probe test")
        self.dg_probe_clean_btn.set_tooltip_text(
            "Rimuove RetroCD-dgVoodoo-Probe solo dopo restore completo, AppDefaults inattivo e baseline integra."
        )
        self.dg_probe_clean_btn.connect(
            "clicked", lambda *_: self.background(self.clean_dgvoodoo_probe)
        )
        tool_row.append(self.dg_probe_clean_btn)

    def _make_dgvoodoo_tab_scrollable(self) -> None:
        """Wrap only the dgVoodoo2 notebook page in a vertical scroller."""
        page_index = None
        page = None
        for index in range(self.notebook.get_n_pages()):
            child = self.notebook.get_nth_page(index)
            if child is None:
                continue
            tab = self.notebook.get_tab_label(child)
            if isinstance(tab, Gtk.Label) and tab.get_text() == "dgVoodoo2":
                page_index = index
                page = child
                break

        if page_index is None or page is None:
            raise RuntimeError("Scheda dgVoodoo2 non trovata: impossibile applicare lo scroll verticale.")

        self.notebook.remove_page(page_index)

        scroller = Gtk.ScrolledWindow()
        scroller.set_hexpand(True)
        scroller.set_vexpand(True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroller.set_child(page)

        self.notebook.insert_page(scroller, Gtk.Label(label="dgVoodoo2"), page_index)
        self.dgvoodoo_scroller = scroller

    def _selected_target_is_probe(self) -> bool:
        try:
            bottle, exe = self.selected_dg_target()
            expected = probe_executable(bottle).resolve(strict=True)
            return exe.resolve(strict=True) == expected
        except Exception:
            return False

    def _probe_cleanup_ready(self) -> bool:
        if self.busy or not self._selected_target_is_probe():
            return False
        try:
            bottle, exe = self.selected_dg_target()
            payload = _dg.inspect_installation(bottle, exe)
            activation = _dg.activation_status(bottle, exe)
            status = probe_status(bottle)
            return (
                payload.state == "inactive"
                and activation.state == "inactive"
                and status.baseline_ok
            )
        except Exception:
            return False

    def _update_dg_action_sensitivity(self, payload=None, activation=None):
        result = super()._update_dg_action_sensitivity(payload, activation)
        button = getattr(self, "dg_probe_clean_btn", None)
        if button is not None:
            button.set_sensitive(self._probe_cleanup_ready())
        return result

    def clean_dgvoodoo_probe(self):
        self._dg_mutation_preflight()
        bottle, exe = self.selected_dg_target()
        expected = probe_executable(bottle).resolve(strict=True)
        if exe.resolve(strict=True) != expected:
            raise _dg.DgVoodooError(
                "Cleanup probe rifiutato: il target selezionato non è RetroCD-dgVoodoo-Probe."
            )

        payload = _dg.inspect_installation(bottle, exe)
        if payload.state != "inactive":
            raise _dg.DgVoodooError(
                "Cleanup probe rifiutato: disinstalla/ripristina prima il payload dgVoodoo2."
            )
        activation = _dg.activation_status(bottle, exe)
        if activation.state != "inactive":
            raise _dg.DgVoodooError(
                "Cleanup probe rifiutato: disattiva/ripristina prima Wine AppDefaults."
            )
        status = probe_status(bottle)
        if not status.baseline_ok:
            raise _dg.DgVoodooError(
                "Cleanup probe rifiutato: la baseline byte-for-byte non è integra."
            )

        clean_probe(bottle)
        GLib.idle_add(self._finish_probe_cleanup_ui, bottle.name, str(bottle.drive_c))
        return "[PASS] Probe di test rimossa completamente dopo baseline byte-for-byte valida."

    def _finish_probe_cleanup_ui(self, bottle_name: str, drive_c: str):
        self._dg_target = None
        self.dg_exe_entry.set_text("")
        self.dg_target_status.set_text(
            f"Bottle: {bottle_name} · drive_c={drive_c} · probe rimossa; seleziona un executable"
        )
        self._set_dg_wrapper_selection(())
        self.refresh_dgvoodoo_local_status()
        return False

    def launch_dgvoodoo_control_panel(self):
        """Launch the graphical CPL without blocking the RetroCD GUI.

        The previous implementation waited synchronously for bottles-cli/bubblejail
        to terminate and therefore reported only that the process had closed.  A
        graphical control panel must instead remain alive independently while the
        RetroCD window stays responsive.  We retain a small diagnostic log so an
        immediate Wine/Bottles exit is visible rather than silently accepted.
        """
        self._dg_mutation_preflight()
        if self._dg_cpl_process is not None and self._dg_cpl_process.poll() is None:
            raise _dg.DgVoodooError("dgVoodooCpl risulta già in esecuzione.")

        bottle, exe = self.selected_dg_target()
        payload = _dg.inspect_installation(bottle, exe)
        if payload.state != "installed":
            raise _dg.DgVoodooError(
                "Control panel disponibile solo con payload integro installato."
            )
        cpl = payload.control_panel
        if cpl is None or cpl.is_symlink() or not cpl.is_file():
            raise _dg.DgVoodooError(
                "dgVoodooCpl.exe gestito non disponibile per questo target."
            )

        log_dir = _dg.manager_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / "dgvoodoo-cpl.log"
        command = [
            "bubblejail", "run", "--wait", _dg.INSTANCE,
            "bottles-cli", "run", "-b", bottle.name, "-e", str(cpl),
        ]
        try:
            log_handle = log_path.open("w", encoding="utf-8")
            process = subprocess.Popen(
                command,
                stdout=log_handle,
                stderr=subprocess.STDOUT,
                text=True,
                start_new_session=True,
            )
            log_handle.close()
        except OSError as exc:
            raise _dg.DgVoodooError(f"Impossibile avviare dgVoodooCpl: {exc}") from exc

        self._dg_cpl_process = process
        self._dg_cpl_log = log_path
        GLib.idle_add(self._start_cpl_watch, process, log_path)
        return (
            f"dgVoodooCpl avviato per {exe.name} · PID {process.pid}. "
            f"RetroCD resta utilizzabile; log diagnostico: {log_path}"
        )

    def _start_cpl_watch(self, process: subprocess.Popen[str], log_path: Path):
        def poll_process():
            code = process.poll()
            if code is None:
                return True
            try:
                text = log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            tail = "\n".join(text.splitlines()[-12:]).strip()
            self._dg_cpl_process = None
            if code == 0:
                message = "dgVoodooCpl terminato normalmente."
                if tail:
                    message += " Log finale:\n" + tail
                self.set_message(message)
            else:
                message = f"dgVoodooCpl terminato con rc={code}."
                if tail:
                    message += " Log finale:\n" + tail
                self.set_message(message, True)
            return False

        GLib.timeout_add_seconds(1, poll_process)
        return False


# Keep the existing dynamic App wiring used by the layered RetroCD GUI.
_dg._life._ext._base.Window = Window
App = _dg.App

if __name__ == "__main__":
    raise SystemExit(App().run())
