#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import sandbox_backend as _sandbox_runtime
from settings_backend import (
    config_dir,
    load_settings,
    migrate_legacy_archive_root,
    normalize_archive_root,
    save_settings,
)


def _initial_archive_root() -> Path:
    migrated = migrate_legacy_archive_root()
    configured = normalize_archive_root(migrated or load_settings().get("archive_root", ""))
    if configured:
        return Path(configured)
    return config_dir() / ".archive-not-configured"


def _set_sandbox_archive_globals(root: Path) -> None:
    root = root.expanduser().resolve(strict=False)
    _sandbox_runtime.DATA_ROOT = root
    _sandbox_runtime.RETROPC_ROOT = root
    _sandbox_runtime.EGLLIBRARY_ROOT = root


_INITIAL_ARCHIVE_ROOT = _initial_archive_root()
_set_sandbox_archive_globals(_INITIAL_ARCHIVE_ROOT)

EXTENDED_GUI = Path(__file__).with_name("bottles-retro-cd-gui.py")
_spec = importlib.util.spec_from_file_location("_bottles_retro_cd_extended", EXTENDED_GUI)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Impossibile caricare la GUI RetroCD: {EXTENDED_GUI}")
_ext = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ext)

Gtk = _ext.Gtk
GLib = _ext.GLib
Gio = _ext.Gio


def _apply_archive_root(root: Path) -> Path:
    root = root.expanduser().resolve(strict=False)
    _set_sandbox_archive_globals(root)
    # The reviewed controller copies these module globals at import time. Keep
    # those references aligned when the user changes archive without restarting.
    _ext._base.DATA_ROOT = root
    _ext._base.RETROPC_ROOT = root
    _ext._base.EGLLIBRARY_ROOT = root
    _ext.RETROPC_ROOT = root
    return root


_apply_archive_root(_INITIAL_ARCHIVE_ROOT)
# Stable metadata for the first public release. Setting these before App/Window
# construction avoids rewriting the preserved reviewed base controller.
_ext._base.APP_ID = "io.github.Paolo86cripple.BottlesRetroCD"
_ext._base.VERSION = "0.4.0"

from cdemu_lifecycle import (  # noqa: E402
    LifecycleReport,
    format_report,
    inspect_lifecycle,
    update_command,
)
from display_backend import (  # noqa: E402
    DISPLAY_AUTO,
    DISPLAY_BACKENDS,
    DISPLAY_LABELS,
    bubblewrap_display_args,
    normalize_display_backend,
)
from retro_optical import (  # noqa: E402
    bubblejail_optical_preflight_invocation,
    format_optical_probe_success,
    optical_probe_script,
    validate_optical_probe_output,
)

UPDATE_HELPER = Path(__file__).with_name("cdemu_update_cli.py")
# Keep a stable reference to the original reviewed controller. The extended
# module replaces its module-level Window symbol after defining its subclass,
# but the real base class remains the second entry in the Python MRO.
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
    """Final release GUI extension for lifecycle and reviewed launch hardening."""

    def __init__(self, app):
        super().__init__(app)
        self._last_lifecycle_report: LifecycleReport | None = None
        self._prepared_update_command: tuple[str, ...] = ()
        self._last_optical_preflight = ""
        self._archive_root = _apply_archive_root(
            Path(normalize_archive_root(self.settings.get("archive_root", "")))
            if normalize_archive_root(self.settings.get("archive_root", ""))
            else _INITIAL_ARCHIVE_ROOT
        )
        self._last_display_backend = normalize_display_backend(
            self.settings.get("display_backend", DISPLAY_AUTO)
        )
        self._install_archive_root_selector()
        self._install_display_backend_selector()
        self.build_lifecycle_tab()

    # ------------------------------------------------------------------
    # Persistent archive boundary.
    # ------------------------------------------------------------------
    def _archive_configured(self) -> bool:
        return bool(normalize_archive_root(self.settings.get("archive_root", "")))

    def _archive_label_text(self) -> str:
        if not self._archive_configured():
            return "Archivio: non configurato"
        return f"Archivio: {self._archive_root}"

    def _install_archive_root_selector(self):
        frame = Gtk.Frame(label="Archivio RetroCD")
        box = self.frame_box(frame)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(row)
        self.archive_root_label = Gtk.Label(
            label=self._archive_label_text(),
            xalign=0,
            wrap=True,
            selectable=True,
            hexpand=True,
        )
        row.append(self.archive_root_label)
        self.archive_root_btn = Gtk.Button(label="Scegli cartella…")
        self.archive_root_btn.connect("clicked", self._choose_archive_root)
        row.append(self.archive_root_btn)

        note = Gtk.Label(
            label=(
                "Radice dei dump Windows PC usati da CDEmu, set multidisco e verifica. "
                "RetroCD salva solo il percorso: non sposta, rinomina o riscrive i dump. "
                "L'archivio non viene esposto persistentemente alla jail; il supporto attivo resta concesso dinamicamente e RO."
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
            raise RuntimeError("Layout Sandbox inatteso: impossibile inserire l'archivio RetroCD.")

    def _choose_archive_root(self, *_):
        if self.sandbox.running():
            self.set_message("Chiudi Bottles/Bubblejail prima di cambiare archivio RetroCD.", True)
            return
        if self.active_bridge_cache or self._live_cleanup_running:
            self.set_message("Termina prima la sessione multidisco e la relativa pulizia cache.", True)
            return

        dialog = Gtk.FileChooserNative.new(
            "Scegli la radice dell'archivio RetroCD",
            self,
            Gtk.FileChooserAction.SELECT_FOLDER,
            "_Seleziona",
            "_Annulla",
        )
        if self._archive_root.is_dir():
            dialog.set_current_folder(Gio.File.new_for_path(str(self._archive_root)))

        def response(dlg, response_id):
            try:
                if response_id != Gtk.ResponseType.ACCEPT:
                    return
                chosen = dlg.get_file()
                raw_path = chosen.get_path() if chosen is not None else None
                if not raw_path:
                    raise RuntimeError("Nessuna directory archivio selezionata.")
                root = Path(raw_path).resolve(strict=True)
                if not root.is_dir():
                    raise RuntimeError(f"Archivio non valido: {root}")

                self.settings["archive_root"] = str(root)
                save_settings(self.settings)
                self._archive_root = _apply_archive_root(root)
                self.archive_root_label.set_text(self._archive_label_text())
                self.reload_saved_disc_sets()
                self.refresh_images()
                self.reload_whitelist()
                self.set_message(f"Archivio RetroCD impostato: {root}. Nessun dump è stato modificato.")
            except Exception as exc:
                self.set_message(f"Impossibile impostare l'archivio RetroCD: {exc}", True)
            finally:
                dlg.destroy()

        dialog.connect("response", response)
        dialog.show()

    # ------------------------------------------------------------------
    # Persistent display backend selection.
    # ------------------------------------------------------------------
    def _install_display_backend_selector(self):
        frame = Gtk.Frame(label="Backend display predefinito")
        box = self.frame_box(frame)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(row)
        row.append(Gtk.Label(label="Display", xalign=0))
        self.display_backend_model = Gtk.StringList.new(
            [DISPLAY_LABELS[name] for name in DISPLAY_BACKENDS]
        )
        self.display_backend_drop = Gtk.DropDown(
            model=self.display_backend_model,
            hexpand=True,
        )
        selected = normalize_display_backend(
            self.settings.get("display_backend", DISPLAY_AUTO)
        )
        self.display_backend_drop.set_selected(DISPLAY_BACKENDS.index(selected))
        self.display_backend_drop.connect(
            "notify::selected",
            self._display_backend_changed,
        )
        row.append(self.display_backend_drop)

        note = Gtk.Label(
            label=(
                "La scelta viene salvata. Auto non forza nulla. Wayland nativo abilita i controlli Proton/CachyOS Wayland. "
                "XWayland lascia la GUI Bottles libera di usare Wayland, ma presenta a Bottles una sessione "
                "X11 per impedire che il toggle Wayland della bottle riattivi winewayland.drv. "
                "La scelta non aggiunge socket o permessi: rete, filesystem, GPU e Retro Optical restano invariati."
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
                "Layout Sandbox inatteso: impossibile inserire il selettore display."
            )

    def _selected_display_backend(self) -> str:
        selected = self.display_backend_drop.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION or selected >= len(DISPLAY_BACKENDS):
            return DISPLAY_AUTO
        return DISPLAY_BACKENDS[selected]

    def _display_backend_changed(self, *_):
        backend = self._selected_display_backend()
        self.settings["display_backend"] = backend
        self._last_display_backend = backend
        try:
            save_settings(self.settings)
        except Exception as exc:
            self.set_message(f"Impossibile salvare il backend display: {exc}", True)

    @staticmethod
    def _inject_display_args(args: list[str], backend: str) -> list[str]:
        display_args = bubblewrap_display_args(backend)
        if not display_args:
            return args
        try:
            separator = args.index("--")
        except ValueError as exc:
            raise RuntimeError(
                "Comando Bubblejail privo del separatore runtime; backend display non applicato."
            ) from exc
        return [*args[:separator], *display_args, *args[separator:]]

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

        backend = self.ui_get(self._selected_display_backend)
        args = self._inject_display_args(args, backend)
        self._last_display_backend = backend

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
        if not self._archive_configured():
            raise RuntimeError("Configura prima la radice dell'archivio RetroCD.")
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
            # tracker. All normal CD/network/multidisc setup still runs via the
            # reviewed controller and dispatches runtime_bubblejail_args() back
            # to this final class for the exact optical preflight.
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
        display_label = DISPLAY_LABELS.get(
            normalize_display_backend(self._last_display_backend),
            DISPLAY_LABELS[DISPLAY_AUTO],
        )
        return (
            str(result)
            + f" · display {display_label}"
            + " · isolamento GPU pre/post e Retro Optical pre/post verificato"
        )

    def run_integration_test(self):
        """Run the reviewed CD→jail test against real temporary host sentinels."""
        if not self._archive_configured():
            raise RuntimeError("Configura prima la radice dell'archivio RetroCD.")
        parent = self._archive_root.parent
        try:
            sentinel_root = Path(tempfile.mkdtemp(prefix=".retrocd-integration-", dir=parent))
        except OSError as exc:
            raise RuntimeError(f"Impossibile creare la sentinel host accanto all'archivio: {exc}") from exc
        (sentinel_root / "progetti").mkdir()
        (sentinel_root / "SteamLibrary").mkdir()
        original_data_root = _ext._base.DATA_ROOT
        _ext._base.DATA_ROOT = sentinel_root
        try:
            result = BASE_CONTROLLER.run_integration_test(self)
        finally:
            _ext._base.DATA_ROOT = original_data_root
            shutil.rmtree(sentinel_root, ignore_errors=True)
        return (
            result.replace("Data/progetti nascosta", "sentinel host non-whitelist A nascosta")
            .replace("Data/SteamLibrary nascosta", "sentinel host non-whitelist B nascosta")
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
        archive = getattr(self, "archive_root_btn", None)
        display = getattr(self, "display_backend_drop", None)
        check = getattr(self, "lifecycle_check_btn", None)
        prepare = getattr(self, "lifecycle_prepare_btn", None)
        copy = getattr(self, "lifecycle_copy_btn", None)
        launch = getattr(self, "lifecycle_launch_update_btn", None)
        if archive is not None:
            archive.set_sensitive(not busy)
        if display is not None:
            display.set_sensitive(not busy)
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
