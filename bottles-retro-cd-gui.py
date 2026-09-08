#!/usr/bin/env python3
"""Bottles Retro CD GUI entrypoint with verifier extension.

The validated rc2/multidisc controller is kept in ``bottles-retro-cd-gui-base.py``.
This entrypoint subclasses it to add the Redump/TOSEC verifier, the reviewed
log-clear action and fail-closed GPU/Retro-Optical Bubblejail validation without
rewriting the established CDEmu/multidisc controller.
"""
from __future__ import annotations

import importlib.util
import signal
from pathlib import Path

BASE_PATH = Path(__file__).with_name("bottles-retro-cd-gui-base.py")
_spec = importlib.util.spec_from_file_location("_bottles_retro_cd_base", BASE_PATH)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Impossibile caricare la GUI base: {BASE_PATH}")
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)

Gtk = _base.Gtk
GLib = _base.GLib
Gio = _base.Gio
RETROPC_ROOT = _base.RETROPC_ROOT

from gpu_backend import (  # noqa: E402
    bubblejail_gpu_probe_invocation,
    validate_gpu_probe_output,
    validate_gpu_runtime,
)
from protection_scanner import (  # noqa: E402
    compare_catalog_protection,
    format_scan,
    scan_image,
)
from retro_optical import (  # noqa: E402
    OpticalExposure,
    bubblejail_optical_probe_invocation,
    format_optical_probe_success,
    optical_probe_script,
    validate_optical_probe_output,
)
from verifier_backend import (  # noqa: E402
    CatalogIndex,
    descriptor_payloads,
    format_verification,
    import_dat_directory,
    update_official_source,
    verifier_data_dir,
)


class Window(_base.Window):
    def __init__(self, app):
        super().__init__(app)
        self.verifier = CatalogIndex()
        self._last_optical_exposure: OpticalExposure | None = None
        self._install_clear_log_button()
        self.build_verifier_tab()
        self.refresh_verifier_status()

    def _install_clear_log_button(self):
        """Add the post-review 'Pulisci log' action beside 'Copia log'."""
        self.clear_log_btn = Gtk.Button(label="Pulisci log")
        self.clear_log_btn.set_tooltip_text(
            "Svuota soltanto il log visualizzato nella sessione corrente; non cancella dump, DAT o cache hash."
        )
        self.clear_log_btn.connect("clicked", self._clear_log)
        parent = self.copy_log_btn.get_parent()
        if isinstance(parent, Gtk.Box):
            parent.append(self.clear_log_btn)
        else:
            raise RuntimeError("Layout Test inatteso: impossibile inserire 'Pulisci log'.")

    def _clear_log(self, *_):
        if self.busy:
            return
        self.test_buffer.set_text("")
        # Do not call set_message(): it appends to the log and would immediately
        # repopulate the buffer that the user explicitly asked to clear.
        self.message.set_text("Log applicazione pulito.")
        self.message.remove_css_class("error")

    # ------------------------------------------------------------------
    # Fail-closed GPU/Bubblejail path from the final sandbox review.
    # ------------------------------------------------------------------
    def selected_gpu(self):
        gpu = super().selected_gpu()
        if gpu is None:
            raise RuntimeError(
                "Nessuna GPU DRM valida rilevata: avvio Bottles rifiutato invece di usare Mesa default."
            )
        validate_gpu_runtime(gpu)
        return gpu

    def _gpu_hidden_nodes(self, gpu) -> tuple[str, ...]:
        return tuple(
            node
            for other in self.gpus
            if other.pci_address != gpu.pci_address
            for node in (other.card_node, other.render_node)
            if node
        )

    def _gpu_probe_script(self, gpu) -> tuple[str, tuple[str, ...]]:
        q = _base.shlex.quote
        hidden_nodes = self._gpu_hidden_nodes(gpu)
        checks: list[str] = []
        for node in (gpu.card_node, gpu.render_node):
            checks.append(
                f"if [ -c {q(node)} ]; then "
                f"printf 'GPU_SELECTED_NODE_OK=%s\\n' {q(node)}; "
                f"else printf 'GPU_SELECTED_NODE_MISSING=%s\\n' {q(node)}; fi"
            )
        for node in hidden_nodes:
            checks.append(
                f"if [ -e {q(node)} ]; then "
                f"printf 'GPU_HIDDEN_NODE_VISIBLE=%s\\n' {q(node)}; "
                f"else printf 'GPU_HIDDEN_NODE_OK=%s\\n' {q(node)}; fi"
            )
        script = """
set +e
printf 'GPU_DRI_PRIME=%s\\n' "$DRI_PRIME"
printf 'GPU_DRI_LIST_BEGIN\\n'
ls -la /dev/dri 2>&1
printf 'GPU_DRI_LIST_END\\n'
""" + "\n".join(checks) + """
if ! command -v vulkaninfo >/dev/null 2>&1; then
    printf 'GPU_VULKANINFO_MISSING=1\\n'
    exit 0
fi
vulkaninfo --summary 2>&1
exit 0
"""
        return script, hidden_nodes

    def _probe_gpu_isolation(self, gpu, *, attached: bool) -> str:
        self.sandbox.ensure_runtime_args_supported()
        script, hidden_nodes = self._gpu_probe_script(gpu)
        args, input_text = bubblejail_gpu_probe_invocation(
            gpu,
            _base.INSTANCE,
            script,
            attached=attached,
        )
        proc = _base.run_cmd(args, input_text=input_text, timeout=40)
        if proc.returncode != 0:
            phase = "post-avvio" if attached else "pre-avvio"
            raise RuntimeError(
                f"Probe GPU Bubblejail {phase} fallito con rc={proc.returncode}:\n{proc.stdout[-4000:]}"
            )
        actual = validate_gpu_probe_output(
            gpu,
            proc.stdout,
            hidden_nodes=hidden_nodes,
            require_dri_prime=not attached,
        )
        phase = "post-avvio" if attached else "pre-avvio"
        return (
            f"[PASS] GPU {phase}: {gpu.pci_address} · {gpu.vendor_id}:{gpu.device_id} · "
            f"{actual.get('deviceName', '—')} · altre GPU nascoste={len(hidden_nodes)}"
        )

    # ------------------------------------------------------------------
    # Retro Optical boundary proof.
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
        """Capture the exact optical policy already computed by the base launcher."""
        if d is not None and raw_on and not d.sr_path:
            raise RuntimeError("Retro Optical: esposizione raw richiesta ma mapping /dev/srX assente.")
        if d is not None and raw_on and sg_on:
            if not d.sg_path or not Path(d.sg_path).exists():
                raise RuntimeError("Retro Optical: esposizione /dev/sgX richiesta ma mapping CDEmu assente.")

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

        raw_expected = bool(d is not None and raw_on and d.sr_path)
        sg_expected = bool(d is not None and raw_on and sg_on and d.sg_path)
        exposure = OpticalExposure(
            mount_expected=bool(bridge is not None or (mount and expose_mount)),
            raw_expected=raw_expected,
            sr_path=d.sr_path if raw_expected else "",
            sg_expected=sg_expected,
            sg_path=d.sg_path if sg_expected else "",
        )
        exposure.validate()
        self._last_optical_exposure = exposure
        return args

    def _probe_optical_isolation(self, exposure: OpticalExposure) -> str:
        args = bubblejail_optical_probe_invocation(
            _base.INSTANCE,
            optical_probe_script(),
        )
        proc = _base.run_cmd(args, timeout=20)
        if proc.returncode != 0:
            raise RuntimeError(
                f"Probe Retro Optical post-avvio fallito con rc={proc.returncode}:\n{proc.stdout[-4000:]}"
            )
        try:
            result = validate_optical_probe_output(exposure, proc.stdout)
        except Exception as exc:
            raise RuntimeError(
                f"{exc}\nOutput probe Retro Optical:\n{proc.stdout[-4000:]}"
            ) from exc
        return format_optical_probe_success(exposure, result)

    def _wait_sandbox_state(self, running: bool, timeout: float = 4.0) -> bool:
        deadline = _base.time.monotonic() + timeout
        while _base.time.monotonic() < deadline:
            try:
                state = self.sandbox.running()
            except Exception:
                state = False
            if state is running:
                return True
            _base.time.sleep(0.1)
        return False

    def _terminate_failed_launch(self, proc) -> None:
        if proc is not None and proc.poll() is None:
            try:
                _base.os.killpg(proc.pid, signal.SIGTERM)
                proc.wait(timeout=3)
            except (ProcessLookupError, _base.subprocess.TimeoutExpired):
                try:
                    _base.os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=2)
                except _base.subprocess.TimeoutExpired:
                    pass
        self._wait_sandbox_state(False, timeout=4.0)
        if self.active_bridge_cache:
            try:
                if not self.sandbox.running():
                    self._cleanup_inactive_live_session()
            except Exception as exc:
                GLib.idle_add(
                    self.append_log,
                    f"Cleanup dopo fallimento GPU/Retro Optical: {exc}",
                    True,
                )

    def test_selected_gpu(self):
        if self.sandbox.running():
            raise RuntimeError("Chiudi Bottles/Bubblejail prima del test GPU.")
        gpu = self.selected_gpu()
        result = self._probe_gpu_isolation(gpu, attached=False)
        if not self._wait_sandbox_state(False, timeout=4.0):
            raise RuntimeError("Il test GPU ha lasciato un'istanza Bubblejail attiva: avvio rifiutato.")
        return result

    def launch_bottles(self):
        # This method runs in the worker thread created by background(). Never
        # touch GTK widgets directly here: marshal all UI work through GLib.
        gpu = self.selected_gpu()
        preflight = self._probe_gpu_isolation(gpu, attached=False)
        GLib.idle_add(self.append_log, preflight)
        if not self._wait_sandbox_state(False, timeout=4.0):
            raise RuntimeError(
                "Il probe GPU pre-avvio non ha chiuso completamente Bubblejail; Bottles non viene avviato."
            )

        # The base launcher owns the complete CD/network/multidisc setup. Capture
        # only its Bubblejail Popen so a failed post-launch proof can terminate
        # the exact process group before returning control to the user. The
        # runtime_bubblejail_args override captures the exact optical exposure
        # chosen by that same base launcher.
        self._last_optical_exposure = None
        captured: list[object] = []
        real_popen = _base.subprocess.Popen

        def tracked_popen(*args, **kwargs):
            proc = real_popen(*args, **kwargs)
            command = args[0] if args else kwargs.get("args")
            if (
                isinstance(command, (list, tuple))
                and command
                and Path(str(command[0])).name == "bubblejail"
                and "--" in command
                and _base.INSTANCE in command
            ):
                captured.append(proc)
            return proc

        _base.subprocess.Popen = tracked_popen
        try:
            result = super().launch_bottles()
        finally:
            _base.subprocess.Popen = real_popen

        if len(captured) != 1:
            proc = captured[-1] if captured else None
            self._terminate_failed_launch(proc)
            raise RuntimeError(
                f"Impossibile identificare in modo univoco il processo Bubblejail avviato ({len(captured)} candidati); "
                "avvio terminato per sicurezza."
            )
        launch_proc = captured[0]

        try:
            if not self._wait_sandbox_state(True, timeout=4.0):
                raise RuntimeError("L'istanza Bubblejail avviata non risulta attiva.")
            postflight = self._probe_gpu_isolation(gpu, attached=True)
            exposure = self._last_optical_exposure
            if exposure is None:
                raise RuntimeError("Policy Retro Optical del lancio non catturata.")
            optical_postflight = self._probe_optical_isolation(exposure)
        except Exception as exc:
            self._terminate_failed_launch(launch_proc)
            raise RuntimeError(
                f"Verifica GPU/Retro Optical post-avvio fallita; Bottles è stato terminato: {exc}"
            ) from exc

        GLib.idle_add(self.append_log, postflight)
        GLib.idle_add(self.append_log, optical_postflight)
        return str(result) + " · isolamento GPU e Retro Optical verificato post-avvio"

    def build_verifier_tab(self):
        page = self.page_box()
        self.add_tab(page, "Verifica")

        intro = Gtk.Label(
            label=(
                "Verifica archivistica Redump/TOSEC: hashing streaming CRC32/MD5/SHA1, indice SQLite e cache "
                "persistente. I dump vengono solo letti: non sono montati, eseguiti, rinominati o modificati. "
                "L'updater DAT usa solo HTTPS verso host ufficiali e installa un aggiornamento solo dopo staging, "
                "validazione XML/ZIP e integrity_check dell'indice."
            ),
            xalign=0,
            wrap=True,
        )
        page.append(intro)

        status_frame = Gtk.Frame(label="Cataloghi")
        page.append(status_frame)
        status_box = self.frame_box(status_frame)
        self.verifier_status = Gtk.Label(label="Indice: —", xalign=0, wrap=True, selectable=True)
        status_box.append(self.verifier_status)

        update_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_box.append(update_row)
        self.update_redump_btn = Gtk.Button(label="Aggiorna Redump PC")
        self.update_redump_btn.connect(
            "clicked", lambda *_: self.background(lambda: self._update_catalog("redump"), report=True)
        )
        update_row.append(self.update_redump_btn)
        self.update_tosec_btn = Gtk.Button(label="Aggiorna TOSEC")
        self.update_tosec_btn.connect(
            "clicked", lambda *_: self.background(lambda: self._update_catalog("tosec"), report=True)
        )
        update_row.append(self.update_tosec_btn)
        self.import_dat_btn = Gtk.Button(label="Importa DAT locali…")
        self.import_dat_btn.connect("clicked", lambda *_: self.choose_dat_directory())
        update_row.append(self.import_dat_btn)

        verify_frame = Gtk.Frame(label="Immagine / set selezionato")
        page.append(verify_frame)
        verify_box = self.frame_box(verify_frame)
        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        verify_box.append(actions)
        self.verify_image_btn = Gtk.Button(label="Verifica immagine")
        self.verify_image_btn.add_css_class("suggested-action")
        self.verify_image_btn.connect(
            "clicked", lambda *_: self.background(self.verify_selected_image, report=True)
        )
        actions.append(self.verify_image_btn)
        self.verify_set_btn = Gtk.Button(label="Verifica set multidisco")
        self.verify_set_btn.connect(
            "clicked", lambda *_: self.background(self.verify_selected_set, report=True)
        )
        actions.append(self.verify_set_btn)
        self.scan_image_btn = Gtk.Button(label="Scansiona protezioni")
        self.scan_image_btn.connect(
            "clicked", lambda *_: self.background(self.scan_selected_image, report=True)
        )
        actions.append(self.scan_image_btn)
        self.verify_scan_btn = Gtk.Button(label="Verifica + confronta scanner")
        self.verify_scan_btn.connect(
            "clicked", lambda *_: self.background(self.verify_and_scan_selected, report=True)
        )
        actions.append(self.verify_scan_btn)

        note = Gtk.Label(
            label=(
                "MATCH 1:1 richiede che tutti i payload del descriptor (es. le tracce FILE di un CUE) "
                "corrispondano a un singolo set DAT completo. I riferimenti CUE/TOC che escono dalla radice "
                "retropc vengono rifiutati. Lo scanner legge ISO9660/Joliet e settori raw direttamente, senza mount."
            ),
            xalign=0,
            wrap=True,
        )
        note.add_css_class("dim-label")
        verify_box.append(note)

        self.verifier_result = Gtk.Label(label="", xalign=0, wrap=True, selectable=True)
        page.append(self.verifier_result)

    def set_busy(self, busy: bool):
        super().set_busy(busy)
        for name in (
            "clear_log_btn", "copy_log_btn", "update_redump_btn", "update_tosec_btn",
            "import_dat_btn", "verify_image_btn", "verify_set_btn", "scan_image_btn", "verify_scan_btn",
        ):
            widget = getattr(self, name, None)
            if widget is not None:
                widget.set_sensitive(not busy)
        if not busy and hasattr(self, "verifier_status"):
            self.refresh_verifier_status()

    def refresh_verifier_status(self):
        try:
            stats = self.verifier.stats()
            root = verifier_data_dir()
            self.verifier_status.set_text(
                f"Indice: {stats['catalogs']} DAT · {stats['games']} giochi · {stats['roms']} record ROM · {root}"
            )
        except Exception as exc:
            self.verifier_status.set_text(f"Indice: errore {exc}")
        return False

    @staticmethod
    def _format_update(report):
        return (
            f"DAT {report.source.upper()} aggiornati: {report.dat_files} file · "
            f"{report.games} giochi · {report.roms} record ROM · indice {report.catalog_path}"
        )

    def _update_catalog(self, source: str):
        report = update_official_source(source, catalog=self.verifier)
        GLib.idle_add(self.refresh_verifier_status)
        return self._format_update(report)

    def choose_dat_directory(self):
        if self.busy:
            return
        dialog = Gtk.FileChooserNative.new(
            "Importa DAT Redump/TOSEC locali",
            self,
            Gtk.FileChooserAction.SELECT_FOLDER,
            "_Importa",
            "_Annulla",
        )

        def response(dlg, response_id):
            try:
                if response_id != Gtk.ResponseType.ACCEPT:
                    return
                chosen = dlg.get_file()
                path = Path(chosen.get_path()).resolve(strict=True) if chosen and chosen.get_path() else None
                if path is None:
                    raise RuntimeError("Nessuna directory DAT selezionata.")
                self.background(lambda: self._import_dat_path(path), report=True)
            except Exception as exc:
                self.set_message(str(exc), True)
            finally:
                dlg.destroy()

        dialog.connect("response", response)
        dialog.show()

    def _import_dat_path(self, path: Path):
        report = import_dat_directory("manual", path, catalog=self.verifier)
        GLib.idle_add(self.refresh_verifier_status)
        return self._format_update(report)

    def verify_selected_image(self):
        image = self.selected_image()
        result = self.verifier.verify(image, RETROPC_ROOT)
        text = format_verification(result)
        GLib.idle_add(self.verifier_result.set_text, text)
        return text

    def verify_selected_set(self):
        descriptors = self.ui_get(
            lambda: tuple(entry.image for entry in self.disc_set.discs)
            if self.disc_set is not None and self.disc_set.discs else ()
        )
        if len(descriptors) < 2:
            raise RuntimeError("Il disco selezionato non appartiene a un set multidisco con almeno due supporti.")
        result = self.verifier.verify_set(descriptors, RETROPC_ROOT)
        parts = [f"Set multidisco: {result.status} · {len(result.results)} supporti"]
        parts.extend(format_verification(item) for item in result.results)
        text = "\n\n".join(parts)
        GLib.idle_add(self.verifier_result.set_text, text)
        return text

    def _scan_descriptor(self, descriptor: Path):
        payloads = descriptor_payloads(descriptor, RETROPC_ROOT)
        scans = []
        for payload in payloads:
            try:
                scans.append(scan_image(payload))
            except Exception as exc:
                scans.append(exc)
        return payloads, scans

    def scan_selected_image(self):
        descriptor = self.selected_image()
        payloads, scans = self._scan_descriptor(descriptor)
        parts = [f"Scanner descriptor: {descriptor.name} · {len(payloads)} payload"]
        for payload, scan in zip(payloads, scans):
            if isinstance(scan, Exception):
                parts.append(f"[WARN] {payload.name}: scanner non applicabile: {scan}")
            else:
                parts.append(format_scan(scan))
        text = "\n\n".join(parts)
        GLib.idle_add(self.verifier_result.set_text, text)
        return text

    def verify_and_scan_selected(self):
        descriptor = self.selected_image()
        verified = self.verifier.verify(descriptor, RETROPC_ROOT)
        payloads, scans = self._scan_descriptor(descriptor)
        parts = [format_verification(verified)]
        declared = verified.exact_matches[0].protection if verified.matched else ""
        for payload, scan in zip(payloads, scans):
            if isinstance(scan, Exception):
                parts.append(f"[WARN] {payload.name}: scanner non applicabile: {scan}")
                continue
            parts.append(format_scan(scan))
            parts.extend(f"[DAT↔SCANNER] {line}" for line in compare_catalog_protection(declared, scan))
        text = "\n\n".join(parts)
        GLib.idle_add(self.verifier_result.set_text, text)
        return text


_base.Window = Window
App = _base.App

if __name__ == "__main__":
    raise SystemExit(App().run())