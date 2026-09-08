#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

EXTENDED_GUI = Path(__file__).with_name("bottles-retro-cd-gui.py")
_spec = importlib.util.spec_from_file_location("_bottles_retro_cd_extended", EXTENDED_GUI)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Impossibile caricare la GUI RetroCD: {EXTENDED_GUI}")
_ext = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ext)

Gtk = _ext.Gtk
GLib = _ext.GLib

from cdemu_lifecycle import (  # noqa: E402
    LifecycleReport,
    format_report,
    inspect_lifecycle,
    update_command,
)
from retro_optical import (  # noqa: E402
    bubblejail_optical_preflight_invocation,
    format_optical_probe_success,
    optical_probe_script,
    validate_optical_probe_output,
)

UPDATE_HELPER = Path(__file__).with_name("cdemu_update_cli.py")
# Keep a stable reference to the original rc2 controller. The extended module
# replaces its module-level Window symbol after defining its subclass, but the
# real base class remains the second entry in the Python MRO.
BASE_CONTROLLER = _ext.Window.__mro__[1]


class _SubprocessProxy:
    """Module-local Popen tracker without mutating subprocess.Popen globally."""

    def __init__(self, real_module, captured: list[object]):
        self._real = real_module
        self._captured = captured

    def __getattr__(self, name):
        return getattr(self._real, name)

    def Popen(self, *args, **kwargs):
        proc = self._real.Popen(*args, **kwargs)
        command = args[0] if args else kwargs.get("args")
        if (
            isinstance(command, (list, tuple))
            and command
            and Path(str(command[0])).name == "bubblejail"
            and "--" in command
            and _ext._base.INSTANCE in command
        ):
            self._captured.append(proc)
        return proc


class Window(_ext.Window):
    """Final Point-5 GUI extension for lifecycle and reviewed launch hardening."""

    def __init__(self, app):
        super().__init__(app)
        self._last_lifecycle_report: LifecycleReport | None = None
        self._prepared_update_command: tuple[str, ...] = ()
        self._last_optical_preflight = ""
        self.build_lifecycle_tab()

    # ------------------------------------------------------------------
    # Final review launch path.
    # ------------------------------------------------------------------
    def runtime_bubblejail_args(
        self,
        d,
        mount,
        *,
        network_on,
        expose_mount,
        raw_on,
        sg_on,
        gpu,
        bridge=None,
    ):
        """Prove the exact final bwrap policy before allowing Bottles to start."""
        args = super().runtime_bubblejail_args(
            d,
            mount,
            network_on=network_on,
            expose_mount=expose_mount,
            raw_on=raw_on,
            sg_on=sg_on,
            gpu=gpu,
            bridge=bridge,
        )
        exposure = self._last_optical_exposure
        if exposure is None:
            raise RuntimeError("Retro Optical: policy runtime non catturata prima del preflight.")

        probe_args, input_text = bubblejail_optical_preflight_invocation(
            args,
            _ext._base.INSTANCE,
            optical_probe_script(),
        )
        proc = _ext._base.run_cmd(probe_args, input_text=input_text, timeout=25)
        if proc.returncode != 0:
            raise RuntimeError(
                f"Probe Retro Optical pre-avvio fallito con rc={proc.returncode}:\n{proc.stdout[-4000:]}"
            )
        try:
            result = validate_optical_probe_output(exposure, proc.stdout)
        except Exception as exc:
            raise RuntimeError(
                f"{exc}\nOutput probe Retro Optical pre-avvio:\n{proc.stdout[-4000:]}"
            ) from exc
        if not self._wait_sandbox_state(False, timeout=4.0):
            raise RuntimeError(
                "Il preflight Retro Optical ha lasciato un'istanza Bubblejail attiva; avvio rifiutato."
            )
        self._last_optical_preflight = format_optical_probe_success(
            exposure,
            result,
            phase="pre-avvio",
        )
        return args

    def launch_bottles(self):
        """Final fail-closed launch: GPU preflight, optical preflight, then postflight."""
        # Runs in the worker created by background(); GTK writes go through GLib.
        gpu = self.selected_gpu()
        gpu_preflight = self._probe_gpu_isolation(gpu, attached=False)
        GLib.idle_add(self.append_log, gpu_preflight)
        if not self._wait_sandbox_state(False, timeout=4.0):
            raise RuntimeError(
                "Il probe GPU pre-avvio non ha chiuso completamente Bubblejail; Bottles non viene avviato."
            )

        self._last_optical_exposure = None
        self._last_optical_preflight = ""
        captured: list[object] = []
        real_subprocess = _ext._base.subprocess
        _ext._base.subprocess = _SubprocessProxy(real_subprocess, captured)
        try:
            # Deliberately bypass the intermediate extension's legacy Popen
            # tracker. All normal rc2 CD/network/multidisc setup still runs via
            # the original controller and dispatches runtime_bubblejail_args()
            # back to this final class for the exact optical preflight.
            result = BASE_CONTROLLER.launch_bottles(self)
        finally:
            _ext._base.subprocess = real_subprocess

        if len(captured) != 1:
            proc = captured[-1] if captured else None
            self._terminate_failed_launch(proc)
            raise RuntimeError(
                f"Impossibile identificare in modo univoco il processo Bubblejail avviato ({len(captured)} candidati); "
                "avvio terminato per sicurezza."
            )
        launch_proc = captured[0]

        optical_preflight = self._last_optical_preflight
        if not optical_preflight:
            self._terminate_failed_launch(launch_proc)
            raise RuntimeError("Prova Retro Optical pre-avvio assente; Bottles è stato terminato.")
        GLib.idle_add(self.append_log, optical_preflight)

        try:
            if not self._wait_sandbox_state(True, timeout=4.0):
                raise RuntimeError("L'istanza Bubblejail avviata non risulta attiva.")
            gpu_postflight = self._probe_gpu_isolation(gpu, attached=True)
            exposure = self._last_optical_exposure
            if exposure is None:
                raise RuntimeError("Policy Retro Optical del lancio non catturata.")
            optical_postflight = self._probe_optical_isolation(exposure)
        except Exception as exc:
            self._terminate_failed_launch(launch_proc)
            raise RuntimeError(
                f"Verifica GPU/Retro Optical post-avvio fallita; Bottles è stato terminato: {exc}"
            ) from exc

        GLib.idle_add(self.append_log, gpu_postflight)
        GLib.idle_add(self.append_log, optical_postflight)
        return (
            str(result)
            + " · isolamento GPU pre/post e Retro Optical pre/post verificato"
        )

    # ------------------------------------------------------------------
    # Point 5B lifecycle GUI.
    # ------------------------------------------------------------------
    def build_lifecycle_tab(self):
        page = self.page_box()
        self.add_tab(page, "Componenti")

        intro = Gtk.Label(
            label=(
                "Lifecycle host-side Retro Optical. Verifica CDEmu, libMirage e il provider VHBA effettivo "
                "senza duplicare il modulo del kernel. Su CachyOS un VHBA fornito direttamente da "
                "linux-cachyos è valido e non richiede vhba-module-dkms."
            ),
            xalign=0,
            wrap=True,
        )
        page.append(intro)

        health_frame = Gtk.Frame(label="Health check")
        page.append(health_frame)
        health_box = self.frame_box(health_frame)
        self.lifecycle_status = Gtk.Label(
            label="Lifecycle Retro Optical: non verificato",
            xalign=0,
            wrap=True,
            selectable=True,
        )
        health_box.append(self.lifecycle_status)

        health_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        health_box.append(health_row)
        self.lifecycle_check_btn = Gtk.Button(label="Ricontrolla")
        self.lifecycle_check_btn.connect(
            "clicked", lambda *_: self.background(self.check_lifecycle_components, report=True)
        )
        health_row.append(self.lifecycle_check_btn)

        self.lifecycle_details = Gtk.Label(
            label="Premi “Ricontrolla” per leggere lo stato reale del sistema.",
            xalign=0,
            wrap=True,
            selectable=True,
        )
        health_box.append(self.lifecycle_details)

        update_frame = Gtk.Frame(label="Aggiornamento esplicito")
        page.append(update_frame)
        update_box = self.frame_box(update_frame)

        update_note = Gtk.Label(
            label=(
                "L'aggiornamento non viene mai eseguito in background. “Prepara aggiornamento” rifà il health "
                "check e costruisce la transazione Arch/CachyOS completa. “Apri in terminale” avvia un helper "
                "interattivo in un terminale: richiede Bottles chiuso, nessun media CDEmu caricato e la parola "
                "AGGIORNA prima di eseguire sudo pacman -Syu. Pacman mantiene il proprio prompt finale."
            ),
            xalign=0,
            wrap=True,
        )
        update_note.add_css_class("dim-label")
        update_box.append(update_note)

        update_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        update_box.append(update_row)
        self.lifecycle_prepare_btn = Gtk.Button(label="Prepara aggiornamento")
        self.lifecycle_prepare_btn.connect(
            "clicked", lambda *_: self.background(self.prepare_lifecycle_update)
        )
        self.lifecycle_prepare_btn.set_sensitive(False)
        update_row.append(self.lifecycle_prepare_btn)

        self.lifecycle_copy_btn = Gtk.Button(label="Copia comando")
        self.lifecycle_copy_btn.connect("clicked", self.copy_lifecycle_update_command)
        self.lifecycle_copy_btn.set_sensitive(False)
        update_row.append(self.lifecycle_copy_btn)

        self.lifecycle_launch_update_btn = Gtk.Button(label="Apri in terminale")
        self.lifecycle_launch_update_btn.add_css_class("suggested-action")
        self.lifecycle_launch_update_btn.connect(
            "clicked", lambda *_: self.background(self.launch_lifecycle_update)
        )
        self.lifecycle_launch_update_btn.set_sensitive(False)
        update_row.append(self.lifecycle_launch_update_btn)

        self.lifecycle_update_preview = Gtk.Label(
            label="Transazione: non preparata",
            xalign=0,
            wrap=True,
            selectable=True,
        )
        update_box.append(self.lifecycle_update_preview)

        boundary = Gtk.Label(
            label=(
                "Confine di sicurezza: CDEmu/libMirage/VHBA restano componenti host-side. Il loro aggiornamento "
                "non modifica la policy Bubblejail e non concede al gioco accesso a /dev/vhba_ctl o al D-Bus CDEmu."
            ),
            xalign=0,
            wrap=True,
        )
        boundary.add_css_class("dim-label")
        page.append(boundary)

    def _runtime_update_preflight(self) -> None:
        if self.sandbox.running():
            raise RuntimeError("Chiudi Bottles/Bubblejail prima di preparare o avviare un aggiornamento.")
        if self.active_bridge_cache:
            raise RuntimeError("Cache multidisco ancora presente: attendi la pulizia o usa Espelli tutto.")
        if self.cdemu is not None:
            loaded = [device.index for device in self.cdemu.devices() if device.loaded]
            if loaded:
                raise RuntimeError(
                    "Media CDEmu ancora caricati: "
                    + ", ".join(f"#{index}" for index in loaded)
                    + ". Usa Espelli tutto prima di aggiornare."
                )

    def _render_lifecycle_report(
        self,
        report: LifecycleReport,
        prepared_command: tuple[str, ...] | None = None,
    ):
        self._last_lifecycle_report = report
        self.lifecycle_status.set_text(
            f"Lifecycle Retro Optical: {'PASS' if report.ok else 'FAIL'} · provider VHBA {report.vhba_provider or 'non determinato'}"
        )
        self.lifecycle_details.set_text(format_report(report))

        if prepared_command is not None:
            self._prepared_update_command = tuple(prepared_command)
        elif not report.ok:
            self._prepared_update_command = ()

        if self._prepared_update_command:
            self.lifecycle_update_preview.set_text(
                "Transazione preparata:\n" + shlex.join(self._prepared_update_command)
            )
        else:
            self.lifecycle_update_preview.set_text("Transazione: non preparata")

        if not self.busy:
            self.lifecycle_prepare_btn.set_sensitive(report.ok)
            prepared = bool(self._prepared_update_command)
            self.lifecycle_copy_btn.set_sensitive(prepared)
            self.lifecycle_launch_update_btn.set_sensitive(prepared)
        return False

    def _clear_prepared_update(self):
        self._prepared_update_command = ()
        if hasattr(self, "lifecycle_update_preview"):
            self.lifecycle_update_preview.set_text("Transazione: non preparata; ricontrolla dopo il terminale.")
            self.lifecycle_copy_btn.set_sensitive(False)
            self.lifecycle_launch_update_btn.set_sensitive(False)
        return False

    def check_lifecycle_components(self):
        report = inspect_lifecycle()
        self._prepared_update_command = ()
        GLib.idle_add(self._render_lifecycle_report, report, None)
        if not report.ok:
            raise RuntimeError("Lifecycle Retro Optical FAIL: " + "; ".join(report.failures))
        return (
            f"[PASS] Lifecycle Retro Optical · {report.vhba_provider} · "
            f"CDEmu {report.daemon_version} · libMirage {report.libmirage_runtime_version} · API {report.interface_version}"
        )

    def prepare_lifecycle_update(self):
        self._runtime_update_preflight()
        report = inspect_lifecycle()
        if not report.ok:
            GLib.idle_add(self._render_lifecycle_report, report, None)
            raise RuntimeError("Health check non valido: aggiornamento non preparato.")
        command = update_command(report)
        GLib.idle_add(self._render_lifecycle_report, report, command)
        return "Aggiornamento Retro Optical preparato: " + shlex.join(command)

    def copy_lifecycle_update_command(self, *_):
        if not self._prepared_update_command:
            self.set_message("Prepara prima l'aggiornamento.", True)
            return
        self.get_clipboard().set(shlex.join(self._prepared_update_command))
        self.set_message("Comando di aggiornamento copiato negli appunti.")

    @staticmethod
    def _terminal_invocation(command: list[str]) -> list[str]:
        candidates = (
            ("konsole", ["--hold", "-e"]),
            ("kitty", ["--hold"]),
            ("alacritty", ["--hold", "-e"]),
            ("xterm", ["-hold", "-e"]),
        )
        for name, prefix in candidates:
            executable = shutil.which(name)
            if executable:
                return [executable, *prefix, *command]
        raise RuntimeError(
            "Nessun terminale supportato trovato (konsole, kitty, alacritty, xterm). "
            "Puoi usare il pulsante 'Copia comando' e lanciarlo manualmente."
        )

    def launch_lifecycle_update(self):
        self._runtime_update_preflight()
        if not self._prepared_update_command:
            raise RuntimeError("Prepara prima l'aggiornamento.")
        if not UPDATE_HELPER.is_file():
            raise RuntimeError(f"Helper di aggiornamento mancante: {UPDATE_HELPER}")

        # Recompute immediately before launching. A changed provider/package set
        # invalidates the preview rather than silently executing a different command.
        report = inspect_lifecycle()
        if not report.ok:
            GLib.idle_add(self._render_lifecycle_report, report, None)
            raise RuntimeError("Health check cambiato o non valido: aggiornamento rifiutato.")
        current_command = update_command(report)
        if tuple(current_command) != tuple(self._prepared_update_command):
            GLib.idle_add(self._render_lifecycle_report, report, None)
            raise RuntimeError(
                "La transazione è cambiata dopo la preview. Premi nuovamente 'Prepara aggiornamento'."
            )

        helper_command = [sys.executable, str(UPDATE_HELPER)]
        terminal_args = self._terminal_invocation(helper_command)
        subprocess.Popen(
            terminal_args,
            cwd=str(Path(__file__).resolve().parent),
            start_new_session=True,
        )
        GLib.idle_add(self._clear_prepared_update)
        return (
            "Terminale di aggiornamento aperto. L'helper rifarà i precheck e richiederà AGGIORNA; "
            "al termine torna qui e premi Ricontrolla."
        )

    def set_busy(self, busy: bool):
        super().set_busy(busy)
        check = getattr(self, "lifecycle_check_btn", None)
        prepare = getattr(self, "lifecycle_prepare_btn", None)
        copy = getattr(self, "lifecycle_copy_btn", None)
        launch = getattr(self, "lifecycle_launch_update_btn", None)
        if check is not None:
            check.set_sensitive(not busy)
        report = getattr(self, "_last_lifecycle_report", None)
        prepared = bool(getattr(self, "_prepared_update_command", ()))
        if prepare is not None:
            prepare.set_sensitive(not busy and report is not None and report.ok)
        if copy is not None:
            copy.set_sensitive(not busy and prepared)
        if launch is not None:
            launch.set_sensitive(not busy and prepared)


# The existing App resolves Window from the base GUI module at activation time.
_ext._base.Window = Window
App = _ext.App

if __name__ == "__main__":
    raise SystemExit(App().run())
