#!/usr/bin/env python3
from __future__ import annotations

import getpass
import os
import shlex
import shutil
import stat
import subprocess
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk

from cdemu_backend import CDEmuBackend, DeviceState
from disc_bridge import DiscBridge
from disc_sets_backend import (
    SavedDiscSet,
    find_saved_set,
    resolve_disc_set,
    load_saved_sets,
    make_new_saved_set,
    make_saved_set,
    save_saved_sets,
    suggest_set_name,
    upsert_saved_set,
)
from gpu_backend import (
    GPUInfo,
    bubblewrap_gpu_args,
    detect_gpus,
    gpu_by_pci,
    parse_vulkan_summary,
    preferred_gpu,
)
from multidisc_backend import DiscEntry, DiscSet
from sandbox_backend import (
    DATA_ROOT,
    EGLLIBRARY_ROOT,
    INSTANCE,
    RETROPC_ROOT,
    SandboxBackend,
    run_cmd,
)
from settings_backend import load_settings, save_settings

APP_ID = "org.local.BottlesRetroCD"
APP_NAME = "Bottles Retro CD"
VERSION = "0.4.0-rc2"
JAIL_CD_TARGET = "/mnt/cdemu"
OPTICAL_EXTENSIONS = {
    ".cue", ".iso", ".mds", ".mdf", ".mdx", ".nrg", ".ccd", ".toc",
    ".cdi", ".bin", ".b5t", ".b6t", ".c2d", ".cif", ".img",
}


class Window(Gtk.ApplicationWindow):
    def __init__(self, app: Gtk.Application):
        super().__init__(application=app, title=f"{APP_NAME} {VERSION}")
        self.set_default_size(760, 560)
        self.set_resizable(True)

        self.cdemu: CDEmuBackend | None = None
        self.sandbox = SandboxBackend(INSTANCE)
        self.devices: list[DeviceState] = []
        self.images: list[Path] = []
        self.disc_set: DiscSet | None = None
        self.saved_disc_sets: list[SavedDiscSet] = []
        self.active_bridge: DiscBridge | None = None
        self.active_bridge_device_index: int | None = None
        self.active_bridge_sr = ""
        self.active_bridge_cache: dict[str, tuple[int, str, str]] = {}
        self.active_bridge_cache_base_count: int | None = None
        self.gpus: list[GPUInfo] = []
        self.settings = load_settings()
        self.busy = False
        self._ui_thread_id = threading.get_ident()
        self._refreshing_gpus = False
        self._live_poll_id: int | None = None
        self._live_cleanup_running = False
        self.connect("close-request", self.on_close_request)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        root.set_margin_top(12)
        root.set_margin_bottom(12)
        root.set_margin_start(12)
        root.set_margin_end(12)
        self.set_child(root)

        head = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        root.append(head)
        title = Gtk.Label(xalign=0, hexpand=True)
        title.set_markup(f"<b>{APP_NAME}</b> <small>{VERSION}</small>")
        head.append(title)
        self.global_status = Gtk.Label(label="inizializzazione…", xalign=1)
        self.global_status.add_css_class("dim-label")
        head.append(self.global_status)

        self.notebook = Gtk.Notebook()
        self.notebook.set_hexpand(True)
        self.notebook.set_vexpand(True)
        root.append(self.notebook)

        self.build_cdemu_tab()
        self.build_sandbox_tab()
        self.build_whitelist_tab()
        self.build_advanced_tab()
        self.build_test_tab()

        self.message = Gtk.Label(label="", xalign=0, wrap=True)
        self.message.add_css_class("dim-label")
        root.append(self.message)

        GLib.idle_add(self.initialize)

    def add_tab(self, child: Gtk.Widget, label: str):
        self.notebook.append_page(child, Gtk.Label(label=label))

    @staticmethod
    def page_box() -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        return box

    @staticmethod
    def frame_box(frame: Gtk.Frame) -> Gtk.Box:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_margin_top(10)
        box.set_margin_bottom(10)
        box.set_margin_start(10)
        box.set_margin_end(10)
        frame.set_child(box)
        return box

    def switch_row(self, parent, title, description, active=False):
        line = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        parent.append(line)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1, hexpand=True)
        line.append(texts)
        texts.append(Gtk.Label(label=title, xalign=0))
        d = Gtk.Label(label=description, xalign=0, wrap=True)
        d.add_css_class("dim-label")
        texts.append(d)
        sw = Gtk.Switch(active=active, valign=Gtk.Align.CENTER)
        line.append(sw)
        return sw

    def build_cdemu_tab(self):
        page = self.page_box()
        self.add_tab(page, "CDEmu")

        frame = Gtk.Frame(label="Drive virtuale")
        page.append(frame)
        box = self.frame_box(frame)

        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        box.append(grid)
        grid.attach(Gtk.Label(label="Device", xalign=0), 0, 0, 1, 1)
        self.device_model = Gtk.StringList.new([])
        self.device_drop = Gtk.DropDown(model=self.device_model, hexpand=True)
        self.device_drop.connect("notify::selected", lambda *_: self.refresh_status())
        grid.attach(self.device_drop, 1, 0, 1, 1)
        refresh = Gtk.Button(label="Aggiorna")
        refresh.connect("clicked", lambda *_: self.refresh_all())
        grid.attach(refresh, 2, 0, 1, 1)

        grid.attach(Gtk.Label(label="Immagine", xalign=0), 0, 1, 1, 1)
        self.image_model = Gtk.StringList.new([])
        self.image_drop = Gtk.DropDown(model=self.image_model, hexpand=True)
        self.image_drop.connect("notify::selected", lambda *_: self.refresh_disc_set())
        grid.attach(self.image_drop, 1, 1, 1, 1)
        refresh_img = Gtk.Button(label="Aggiorna")
        refresh_img.connect("clicked", lambda *_: self.refresh_images())
        grid.attach(refresh_img, 2, 1, 1, 1)

        scope = Gtk.Label(label=f"Immagini consentite: {RETROPC_ROOT}", xalign=0, wrap=True)
        scope.add_css_class("dim-label")
        box.append(scope)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        box.append(actions)
        self.load_btn = Gtk.Button(label="Carica")
        self.load_btn.add_css_class("suggested-action")
        self.load_btn.connect("clicked", lambda *_: self.background(self.load_selected_image))
        actions.append(self.load_btn)
        self.eject_btn = Gtk.Button(label="Espelli")
        self.eject_btn.connect("clicked", lambda *_: self.background(self.eject_selected_device))
        actions.append(self.eject_btn)

        mdframe = Gtk.Frame(label="Multidisco")
        page.append(mdframe)
        mdbox = self.frame_box(mdframe)
        mdrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        mdbox.append(mdrow)
        self.disc_model = Gtk.StringList.new([])
        self.disc_drop = Gtk.DropDown(model=self.disc_model, hexpand=True)
        mdrow.append(self.disc_drop)
        self.disc_prev_btn = Gtk.Button(label="◀ Precedente")
        self.disc_prev_btn.connect("clicked", lambda *_: self.background(lambda: self.swap_relative_disc(-1)))
        mdrow.append(self.disc_prev_btn)
        self.disc_swap_btn = Gtk.Button(label="Cambia disco")
        self.disc_swap_btn.add_css_class("suggested-action")
        self.disc_swap_btn.connect("clicked", lambda *_: self.background(self.swap_selected_disc))
        mdrow.append(self.disc_swap_btn)
        self.disc_next_btn = Gtk.Button(label="Successivo ▶")
        self.disc_next_btn.connect("clicked", lambda *_: self.background(lambda: self.swap_relative_disc(1)))
        mdrow.append(self.disc_next_btn)
        self.live_multidisc_switch = self.switch_row(
            mdbox,
            "Cambio live mentre Bottles è aperto",
            "Precarica il set su drive CDEmu host-side separati, tutti montati RO e invisibili come device "
            "alla jail. Wine riceve il cambio reale sul solo /dev/srX attivo; /mnt/cdemu segue il disco "
            "selezionato tramite il bridge statico già validato.",
            False,
        )
        setrow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        mdbox.append(setrow)
        self.save_disc_set_btn = Gtk.Button(label="Crea set da questo disco")
        self.save_disc_set_btn.set_tooltip_text(
            "Se il disco non appartiene ancora a un set, crea un set esplicito partendo solo dal "
            "descriptor selezionato. Non copia, rinomina o modifica immagini/CUE."
        )
        self.save_disc_set_btn.connect("clicked", lambda *_: self.background(self.save_current_disc_set))
        setrow.append(self.save_disc_set_btn)
        self.add_disc_to_set_btn = Gtk.Button(label="Aggiungi disco…")
        self.add_disc_to_set_btn.set_tooltip_text(
            "Aggiunge al set un descriptor originale anche se si trova in un'altra cartella sotto retropc."
        )
        self.add_disc_to_set_btn.connect("clicked", lambda *_: self.choose_disc_for_saved_set())
        setrow.append(self.add_disc_to_set_btn)
        self.forget_disc_set_btn = Gtk.Button(label="Dimentica set")
        self.forget_disc_set_btn.set_tooltip_text(
            "Elimina solo il metadato del set; i dump originali non vengono toccati."
        )
        self.forget_disc_set_btn.connect("clicked", lambda *_: self.background(self.forget_current_disc_set))
        setrow.append(self.forget_disc_set_btn)

        fidelity = Gtk.Label(
            label=(
                "Modalità archivistica: i set salvano soltanto riferimenti ai file originali Redump/TOSEC. "
                "Nessun file viene spostato, rinominato, copiato o riscritto; cartelle separate sono supportate."
            ),
            xalign=0,
            wrap=True,
        )
        fidelity.add_css_class("dim-label")
        mdbox.append(fidelity)

        self.multidisc_status = Gtk.Label(label="Multidisco: seleziona un'immagine", xalign=0, wrap=True)
        mdbox.append(self.multidisc_status)

        mframe = Gtk.Frame(label="Mount")
        page.append(mframe)
        mbox = self.frame_box(mframe)
        self.udisks_switch = self.switch_row(
            mbox,
            "UDisks2 read-only",
            "Quando possibile monta /dev/srX tramite UDisks2 e verifica il flag ro.",
            True,
        )
        self.mount_status = Gtk.Label(label="Mount: —", xalign=0, wrap=True)
        mbox.append(self.mount_status)

        self.cdemu_status = Gtk.Label(label="CDEmu: —", xalign=0, wrap=True)
        page.append(self.cdemu_status)

    def build_sandbox_tab(self):
        page = self.page_box()
        self.add_tab(page, "Sandbox")

        gframe = Gtk.Frame(label="GPU per questo avvio")
        page.append(gframe)
        gbox = self.frame_box(gframe)
        grow = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        gbox.append(grow)
        self.gpu_model = Gtk.StringList.new([])
        self.gpu_drop = Gtk.DropDown(model=self.gpu_model, hexpand=True)
        self.gpu_drop.connect("notify::selected", self.gpu_changed)
        grow.append(self.gpu_drop)
        self.gpu_refresh_btn = Gtk.Button(label="Aggiorna GPU")
        self.gpu_refresh_btn.connect("clicked", lambda *_: self.refresh_gpus())
        grow.append(self.gpu_refresh_btn)
        self.gpu_test_btn = Gtk.Button(label="Test Vulkan")
        self.gpu_test_btn.connect("clicked", lambda *_: self.background(self.test_selected_gpu, report=True))
        grow.append(self.gpu_test_btn)
        self.gpu_status = Gtk.Label(label="GPU: rilevamento non eseguito", xalign=0, wrap=True)
        gbox.append(self.gpu_status)
        gpu_note = Gtk.Label(
            label=(
                "La selezione usa l'indirizzo PCI stabile, non card1/card2. "
                "L'iGPU è preferita al primo avvio; la scelta viene salvata in config.toml. "
                "DRI_PRIME seleziona la GPU per OpenGL/Vulkan e Vulkan viene limitato alla GPU scelta."
            ),
            xalign=0,
            wrap=True,
        )
        gpu_note.add_css_class("dim-label")
        gbox.append(gpu_note)

        frame = Gtk.Frame(label="Permessi per questo avvio")
        page.append(frame)
        box = self.frame_box(frame)
        self.network_switch = self.switch_row(
            box,
            "Rete",
            "OFF di default. ON aggiunge la rete solo a questo avvio, senza modificare services.toml.",
            False,
        )
        self.expose_mount_switch = self.switch_row(
            box,
            "Esporre mount RO come /mnt/cdemu",
            "Condivide solo il mount del disco corrente, mai tutto /run/media.",
            True,
        )
        self.raw_switch = self.switch_row(
            box,
            "Esporre /dev/srX",
            "Compatibilità avanzata: espone solo il block device ottico mappato da CDEmu. "
            "Il mount filesystem resta comunque obbligatoriamente RO. "
            "Abilitalo solo per giochi che devono interrogare il lettore fisico.",
            False,
        )
        self.sg_switch = self.switch_row(
            box,
            "Esporre /dev/sgX",
            "SCSI generic avanzato; OFF salvo necessità specifica.",
            False,
        )
        self.raw_switch.connect("notify::active", self.raw_changed)
        self.raw_changed()

        sframe = Gtk.Frame(label="Profilo Bubblejail")
        page.append(sframe)
        sbox = self.frame_box(sframe)
        self.sandbox_status = Gtk.Label(label="Bubblejail: —", xalign=0, wrap=True)
        self.fs_status = Gtk.Label(label="Filesystem: —", xalign=0, wrap=True)
        sbox.append(self.sandbox_status)
        sbox.append(self.fs_status)
        audit_btn = Gtk.Button(label="Verifica profilo")
        audit_btn.connect("clicked", lambda *_: self.refresh_sandbox_status())
        sbox.append(audit_btn)

        self.launch_btn = Gtk.Button(label="Avvia Bottles")
        self.launch_btn.add_css_class("suggested-action")
        self.launch_btn.set_tooltip_text(
            "Avvia l'istanza Bubblejail Bottles con la whitelist corrente. "
            "La rete vale solo per questo avvio; il CD è opzionale."
        )
        self.launch_btn.connect("clicked", lambda *_: self.background(self.launch_bottles))
        page.append(self.launch_btn)

        launch_note = Gtk.Label(
            label=(
                "Test operativo: Bottles può essere avviato anche senza CD. "
                "Se il device CDEmu selezionato contiene un disco, il mount/device ottico "
                "vengono aggiunti secondo le opzioni sopra."
            ),
            xalign=0,
            wrap=True,
        )
        launch_note.add_css_class("dim-label")
        page.append(launch_note)


    def build_whitelist_tab(self):
        page = self.page_box()
        self.add_tab(page, "Whitelist")

        intro = Gtk.Label(
            label=(
                "Queste sono le directory persistenti esposte a Bottles tramite [root_share]. "
                "RW consente scrittura; RO è sola lettura. Le modifiche vengono applicate direttamente "
                "al services.toml dell’istanza e viene creato un backup automatico."
            ),
            xalign=0,
            wrap=True,
        )
        page.append(intro)

        self.whitelist_rw: list[str] = []
        self.whitelist_ro: list[str] = []

        rw_frame = Gtk.Frame(label="Read/Write")
        page.append(rw_frame)
        rw_box = self.frame_box(rw_frame)
        self.rw_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.rw_listbox.set_size_request(-1, 90)
        rw_box.append(self.rw_listbox)
        rw_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        rw_box.append(rw_actions)
        add_rw = Gtk.Button(label="Aggiungi cartella…")
        add_rw.connect("clicked", lambda *_: self.choose_whitelist_folder("rw"))
        rw_actions.append(add_rw)
        del_rw = Gtk.Button(label="Rimuovi selezionata")
        del_rw.connect("clicked", lambda *_: self.remove_whitelist_selected("rw"))
        rw_actions.append(del_rw)

        ro_frame = Gtk.Frame(label="Read-only")
        page.append(ro_frame)
        ro_box = self.frame_box(ro_frame)
        self.ro_listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self.ro_listbox.set_size_request(-1, 90)
        ro_box.append(self.ro_listbox)
        ro_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ro_box.append(ro_actions)
        add_ro = Gtk.Button(label="Aggiungi cartella…")
        add_ro.connect("clicked", lambda *_: self.choose_whitelist_folder("ro"))
        ro_actions.append(add_ro)
        del_ro = Gtk.Button(label="Rimuovi selezionata")
        del_ro.connect("clicked", lambda *_: self.remove_whitelist_selected("ro"))
        ro_actions.append(del_ro)

        warning = Gtk.Label(
            label=(
                "Protezione: la GUI rifiuta HOME reale, Data intero, bind annidati e alberi di sistema troppo ampi. "
                "Il mount CDEmu non va aggiunto qui: viene concesso dinamicamente e RO."
            ),
            xalign=0,
            wrap=True,
        )
        warning.add_css_class("dim-label")
        page.append(warning)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        page.append(actions)
        reload_btn = Gtk.Button(label="Ricarica dal profilo")
        reload_btn.connect("clicked", lambda *_: self.reload_whitelist())
        actions.append(reload_btn)
        restore_btn = Gtk.Button(label="Ripristina backup")
        restore_btn.connect("clicked", lambda *_: self.background(self.restore_whitelist_backup))
        actions.append(restore_btn)
        apply_btn = Gtk.Button(label="Applica whitelist")
        apply_btn.add_css_class("suggested-action")
        apply_btn.connect("clicked", lambda *_: self.background(self.apply_whitelist))
        actions.append(apply_btn)

        self.whitelist_status = Gtk.Label(label="Whitelist: —", xalign=0, wrap=True)
        page.append(self.whitelist_status)

    def build_advanced_tab(self):
        page = self.page_box()
        self.add_tab(page, "Avanzate")
        frame = Gtk.Frame(label="Emulazioni CDEmu")
        page.append(frame)
        box = self.frame_box(frame)
        note = Gtk.Label(
            label="Le opzioni sono applicate direttamente al device CDEmu via D-Bus, come in gCDEmu.",
            xalign=0,
            wrap=True,
        )
        note.add_css_class("dim-label")
        box.append(note)
        self.dpm_switch = self.switch_row(box, "DPM emulation", "Compatibilità con controlli basati sulla densità/posizione fisica.", False)
        self.tr_switch = self.switch_row(box, "Transfer-rate emulation", "Emula la velocità di lettura del drive ottico.", False)
        self.bad_switch = self.switch_row(box, "Bad-sector emulation", "Riproduce settori errati descritti dall'immagine.", False)
        self.css_switch = self.switch_row(box, "DVD CSS reporting", "Segnala CSS/CPPM al software guest.", False)
        apply_btn = Gtk.Button(label="Applica al device selezionato")
        apply_btn.connect("clicked", lambda *_: self.background(self.apply_options_selected))
        box.append(apply_btn)

    def build_test_tab(self):
        page = self.page_box()
        self.add_tab(page, "Test")

        intro = Gtk.Label(
            label=(
                "Il riquadro sotto è anche il log applicativo cumulativo: registra test, avvii, cambi disco, "
                "errori e cleanup. I test non installano nulla e non avviano giochi; il test CDEmu crea un drive "
                "temporaneo, lo usa e lo rimuove, mentre il test sandbox apre solo una debug shell Bubblejail automatizzata."
            ),
            xalign=0,
            wrap=True,
        )
        page.append(intro)

        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        page.append(row)
        self.test_cdemu_btn = Gtk.Button(label="Test CDEmu + UDisks2")
        self.test_cdemu_btn.connect("clicked", lambda *_: self.background(self.run_cdemu_test, report=True))
        row.append(self.test_cdemu_btn)
        self.test_sandbox_btn = Gtk.Button(label="Test Bubblejail")
        self.test_sandbox_btn.connect("clicked", lambda *_: self.background(self.run_sandbox_test, report=True))
        row.append(self.test_sandbox_btn)
        self.test_integration_btn = Gtk.Button(label="Test CD → Bubblejail")
        self.test_integration_btn.connect("clicked", lambda *_: self.background(self.run_integration_test, report=True))
        row.append(self.test_integration_btn)
        self.test_all_btn = Gtk.Button(label="Esegui tutti")
        self.test_all_btn.add_css_class("suggested-action")
        self.test_all_btn.connect("clicked", lambda *_: self.background(self.run_all_tests, report=True))
        row.append(self.test_all_btn)
        self.test_bridge_btn = Gtk.Button(label="Test bridge multidisco")
        self.test_bridge_btn.connect("clicked", lambda *_: self.background(self.run_disc_bridge_test, report=True))
        row.append(self.test_bridge_btn)

        row2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        page.append(row2)
        self.test_disc_cache_btn = Gtk.Button(label="Test cache multidisco")
        self.test_disc_cache_btn.connect("clicked", lambda *_: self.background(self.run_disc_cache_test, report=True))
        row2.append(self.test_disc_cache_btn)

        self.copy_log_btn = Gtk.Button(label="Copia log")
        self.copy_log_btn.connect("clicked", self.copy_test_log)
        row.append(self.copy_log_btn)

        self.test_network_check = Gtk.CheckButton(label="Testa anche la rete temporanea ON (contatta example.com)")
        self.test_network_check.set_active(False)
        page.append(self.test_network_check)

        scroll = Gtk.ScrolledWindow(vexpand=True, hexpand=True)
        page.append(scroll)
        self.test_view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True)
        self.test_view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        scroll.set_child(self.test_view)
        self.test_buffer = self.test_view.get_buffer()
        self.test_buffer.set_text("Log applicazione avviato.\n")

    def initialize(self):
        try:
            self.cdemu = CDEmuBackend(use_system_bus=False, autostart=True)
            self.cdemu.subscribe(lambda *_: GLib.idle_add(self.refresh_all))
            self.global_status.set_text(
                f"CDEmu {self.cdemu.daemon_version()} · libMirage {self.cdemu.library_version()}"
            )
        except Exception as exc:
            self.global_status.set_text("CDEmu non connesso")
            self.set_message(f"Connessione CDEmu fallita: {exc}", True)
        self.reload_whitelist()
        self.reload_saved_disc_sets()
        self.refresh_gpus()
        self.refresh_all()
        return False

    def on_close_request(self, *_):
        if self._live_cleanup_running:
            self.set_message("Pulizia cache multidisco in corso: attendi che termini prima di chiudere la GUI.", True)
            return True
        if self.busy:
            self.set_message("Operazione in corso: attendi che termini prima di chiudere la GUI.", True)
            return True
        if self.active_bridge_cache and self.sandbox.running():
            self.set_message(
                "Sessione multidisco live attiva: chiudi prima Bottles, così la GUI può smontare "
                "e rimuovere in sicurezza i drive CDEmu di cache.",
                True,
            )
            return True
        if self.active_bridge_cache:
            self._start_live_cleanup()
            return True
        if self.cdemu is not None:
            self.cdemu.close()
        return False

    def _poll_live_session(self):
        if not self.active_bridge_cache:
            self._live_poll_id = None
            return False
        if self._live_cleanup_running:
            self._live_poll_id = None
            return False
        if self.sandbox.running():
            return True
        if self.busy:
            return True
        self._live_poll_id = None
        self._start_live_cleanup()
        return False

    def _start_live_cleanup(self):
        if self._live_cleanup_running or not self.active_bridge_cache:
            return False
        if self.sandbox.running():
            self.set_message("Cleanup cache multidisco rinviato: Bottles/Bubblejail è ancora attivo.", True)
            return False

        self._live_cleanup_running = True
        self.set_message("Bottles chiuso: pulizia cache multidisco in corso…")
        self.set_busy(True)

        def worker():
            try:
                warnings = self._cleanup_inactive_live_session()
                error = None
            except Exception as exc:
                warnings = []
                error = str(exc)
            GLib.idle_add(self._finish_live_cleanup, warnings, error)

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _finish_live_cleanup(self, warnings, error):
        self._live_cleanup_running = False
        self.set_busy(False)
        self.device_drop.set_sensitive(True)
        self.refresh_devices()
        if error:
            self.set_message(f"Cleanup cache multidisco fallito: {error}", True)
        elif warnings:
            self.set_message("Cleanup cache multidisco: " + "; ".join(warnings), True)
        else:
            self.set_message("Sessione multidisco terminata: cache CDEmu ripulita.")
        return False

    def _ensure_live_poll(self):
        if self._live_poll_id is None and not self._live_cleanup_running:
            self._live_poll_id = GLib.timeout_add_seconds(3, self._poll_live_session)

    def append_log(self, text: str, error: bool = False):
        if not text or not hasattr(self, "test_buffer"):
            return
        stamp = time.strftime("%H:%M:%S")
        prefix = "ERROR · " if error else ""
        payload = str(text).rstrip("\n")
        end = self.test_buffer.get_end_iter()
        self.test_buffer.insert(end, f"[{stamp}] {prefix}{payload}\n")

    def set_message(self, text: str, error: bool = False):
        self.message.set_text(text)
        if error:
            self.message.add_css_class("error")
        else:
            self.message.remove_css_class("error")
        self.append_log(text, error)

    def ui_get(self, getter):
        """Read GTK state on the GTK main thread, even when called by a worker."""
        if threading.get_ident() == self._ui_thread_id:
            return getter()

        done = threading.Event()
        result = {}

        def invoke():
            try:
                result["value"] = getter()
            except BaseException as exc:
                result["error"] = exc
            finally:
                done.set()
            return False

        GLib.idle_add(invoke)
        if not done.wait(5.0):
            raise RuntimeError("Timeout leggendo lo stato GTK dal main thread.")
        if "error" in result:
            raise result["error"]
        return result.get("value")

    def set_busy(self, busy: bool):
        self.busy = busy
        for widget in (
            self.load_btn, self.eject_btn, self.launch_btn,
            self.device_drop, self.image_drop, self.disc_drop, self.gpu_drop,
            self.disc_prev_btn, self.disc_swap_btn, self.disc_next_btn,
            self.save_disc_set_btn, self.add_disc_to_set_btn, self.forget_disc_set_btn,
            self.gpu_refresh_btn, self.gpu_test_btn,
            self.test_cdemu_btn, self.test_sandbox_btn, self.test_integration_btn, self.test_all_btn, self.test_bridge_btn,
            self.test_disc_cache_btn,
        ):
            widget.set_sensitive(not busy)
        if not busy:
            self.refresh_disc_set()
            self.refresh_devices()

    def selected_gpu(self) -> GPUInfo | None:
        if not self.gpus:
            return None
        idx = self.ui_get(self.gpu_drop.get_selected)
        if idx == Gtk.INVALID_LIST_POSITION or idx >= len(self.gpus):
            return preferred_gpu(self.gpus)
        return self.gpus[idx]

    def refresh_gpu_status(self):
        if not self.gpus:
            self.gpu_status.set_text("GPU: nessuna GPU DRM con render node rilevata")
            return False
        idx = self.gpu_drop.get_selected()
        if idx == Gtk.INVALID_LIST_POSITION or idx >= len(self.gpus):
            gpu = preferred_gpu(self.gpus)
        else:
            gpu = self.gpus[idx]
        if gpu is None:
            self.gpu_status.set_text("GPU: selezione non disponibile")
            return False
        vram = f" · VRAM {gpu.vram_bytes / 1024**3:.1f} GiB" if gpu.vram_bytes is not None else ""
        driver = f" · driver {gpu.driver}" if gpu.driver else ""
        self.gpu_status.set_text(
            f"Selezionata: {gpu.kind_label} · {gpu.name} · PCI {gpu.pci_address} · "
            f"{Path(gpu.render_node).name or 'render node —'}{vram}{driver}"
        )
        return False

    def refresh_gpus(self):
        previous = ""
        if self.gpus and hasattr(self, "gpu_drop"):
            idx = self.gpu_drop.get_selected()
            if idx != Gtk.INVALID_LIST_POSITION and idx < len(self.gpus):
                previous = self.gpus[idx].pci_address
        saved = str(self.settings.get("gpu_pci", ""))

        self._refreshing_gpus = True
        try:
            self.gpus = detect_gpus()
            self.gpu_model.splice(0, self.gpu_model.get_n_items(), [gpu.label for gpu in self.gpus])
            chosen = gpu_by_pci(self.gpus, previous or saved) or preferred_gpu(self.gpus)
            if chosen is not None:
                self.gpu_drop.set_selected(self.gpus.index(chosen))
                if saved != chosen.pci_address:
                    self.settings["gpu_pci"] = chosen.pci_address
                    save_settings(self.settings)
            elif self.gpu_model.get_n_items() == 0:
                self.settings["gpu_pci"] = ""
        finally:
            self._refreshing_gpus = False
        self.refresh_gpu_status()
        return False

    def gpu_changed(self, *_):
        if self._refreshing_gpus:
            return
        idx = self.gpu_drop.get_selected()
        if idx != Gtk.INVALID_LIST_POSITION and idx < len(self.gpus):
            self.settings["gpu_pci"] = self.gpus[idx].pci_address
            save_settings(self.settings)
        self.refresh_gpu_status()

    def test_selected_gpu(self):
        self.sandbox.ensure_runtime_args_supported()
        if self.sandbox.running():
            raise RuntimeError("Chiudi Bottles/Bubblejail prima del test GPU.")
        gpu = self.selected_gpu()
        if gpu is None:
            raise RuntimeError("Nessuna GPU selezionabile rilevata.")

        args = ["bubblejail", "run"] + bubblewrap_gpu_args(gpu) + ["--debug-shell", INSTANCE]
        selected_nodes = [node for node in (gpu.card_node, gpu.render_node) if node]
        hidden_nodes = [
            node
            for other in self.gpus
            if other.pci_address != gpu.pci_address
            for node in (other.card_node, other.render_node)
            if node
        ]
        checks = []
        for node in selected_nodes:
            checks.append(
                f"if [ -c {shlex.quote(node)} ]; then "
                f"printf 'GPU_SELECTED_NODE_OK=%s\\n' {shlex.quote(node)}; "
                f"else printf 'GPU_SELECTED_NODE_MISSING=%s\\n' {shlex.quote(node)}; fi"
            )
        for node in hidden_nodes:
            checks.append(
                f"if [ -e {shlex.quote(node)} ]; then "
                f"printf 'GPU_HIDDEN_NODE_VISIBLE=%s\\n' {shlex.quote(node)}; "
                f"else printf 'GPU_HIDDEN_NODE_OK=%s\\n' {shlex.quote(node)}; fi"
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
        proc = run_cmd(args, input_text=script, timeout=40)
        if "GPU_VULKANINFO_MISSING=1" in proc.stdout:
            raise RuntimeError("vulkaninfo non è disponibile dentro Bubblejail.")
        missing_selected = [
            line.split("=", 1)[1]
            for line in proc.stdout.splitlines()
            if line.startswith("GPU_SELECTED_NODE_MISSING=")
        ]
        visible_hidden = [
            line.split("=", 1)[1]
            for line in proc.stdout.splitlines()
            if line.startswith("GPU_HIDDEN_NODE_VISIBLE=")
        ]
        if missing_selected:
            raise RuntimeError(
                "Nodi DRM selezionati mancanti nella jail: " + ", ".join(missing_selected)
            )
        if visible_hidden:
            raise RuntimeError(
                "Isolamento GPU fallito; nodi della GPU non selezionata ancora visibili: "
                + ", ".join(visible_hidden)
            )
        devices = parse_vulkan_summary(proc.stdout)
        if len(devices) != 1:
            raise RuntimeError(
                f"Il test Vulkan attende una sola GPU esposta, trovate {len(devices)}.\n{proc.stdout[-4000:]}"
            )
        actual = devices[0]
        vendor = actual.get("vendorID", "").lower().removeprefix("0x").zfill(4)
        device = actual.get("deviceID", "").lower().removeprefix("0x").zfill(4)
        if vendor != gpu.vendor_id.zfill(4) or device != gpu.device_id.zfill(4):
            raise RuntimeError(
                f"GPU Vulkan diversa da quella richiesta: attesa {gpu.vendor_id}:{gpu.device_id}, "
                f"ottenuta {vendor}:{device} ({actual.get('deviceName', 'nome sconosciuto')})."
            )
        return "\n".join([
            f"[INFO] GPU richiesta: {gpu.kind_label} · {gpu.name} · PCI {gpu.pci_address}",
            f"[PASS] DRI_PRIME: {gpu.mesa_dri_prime}",
            f"[PASS] nodi DRM selezionati visibili: {', '.join(selected_nodes)}",
            f"[PASS] nodi DRM altre GPU assenti: {len(hidden_nodes)}",
            "[PASS] Vulkan espone una sola GPU",
            f"[PASS] PCI vendor/device: {vendor}:{device}",
            f"[INFO] Vulkan deviceName: {actual.get('deviceName', '—')}",
        ])

    def background(self, fn, report: bool = False):
        if self.busy:
            return
        self.set_busy(True)
        if report:
            self.append_log("Test in esecuzione…")

        def worker():
            try:
                value = fn()
                GLib.idle_add(self.finish_background, value, None, report)
            except Exception as exc:
                GLib.idle_add(self.finish_background, None, str(exc), report)

        threading.Thread(target=worker, daemon=True).start()

    def finish_background(self, value, error, report):
        self.set_busy(False)
        if error:
            self.set_message(f"FAIL: {error}" if report else error, True)
        else:
            self.set_message(str(value or "Operazione completata."))
        self.refresh_all()
        return False

    def refresh_all(self):
        self.refresh_images()
        self.refresh_devices()
        self.refresh_sandbox_status()
        return False

    def refresh_images(self):
        old = self.image_drop.get_selected() if hasattr(self, "image_drop") else 0
        self.images = []
        if RETROPC_ROOT.exists():
            root = RETROPC_ROOT.resolve(strict=False)
            for dirpath, dirnames, filenames in os.walk(RETROPC_ROOT, followlinks=False):
                dirnames[:] = [d for d in dirnames if not (Path(dirpath) / d).is_symlink()]
                for name in filenames:
                    p = Path(dirpath) / name
                    if p.suffix.lower() not in OPTICAL_EXTENSIONS:
                        continue
                    try:
                        r = p.resolve(strict=True)
                    except OSError:
                        continue
                    if r.is_relative_to(root):
                        self.images.append(r)
            self.images.sort(key=lambda p: str(p).casefold())
        labels = [str(p.relative_to(RETROPC_ROOT.resolve(strict=False))) for p in self.images]
        self.image_model.splice(0, self.image_model.get_n_items(), labels)
        if self.images:
            self.image_drop.set_selected(min(old, len(self.images) - 1) if old != Gtk.INVALID_LIST_POSITION else 0)
        self.refresh_disc_set()
        return False

    def reload_saved_disc_sets(self):
        try:
            self.saved_disc_sets = load_saved_sets(RETROPC_ROOT)
        except Exception as exc:
            self.saved_disc_sets = []
            self.set_message(str(exc), True)
        return False

    def refresh_disc_set(self):
        if not self.images:
            self.disc_set = None
            self.disc_model.splice(0, self.disc_model.get_n_items(), [])
            self.multidisc_status.set_text("Multidisco: nessuna immagine")
            self.disc_drop.set_sensitive(False)
            self.live_multidisc_switch.set_sensitive(False)
            self.forget_disc_set_btn.set_sensitive(False)
            return False
        try:
            selected = self.selected_image()
            saved = find_saved_set(selected, self.saved_disc_sets)
            self.save_disc_set_btn.set_label(
                "Salva set" if saved is not None else "Crea set da questo disco"
            )
            disc_set = resolve_disc_set(
                selected, self.images, RETROPC_ROOT, self.saved_disc_sets
            )
            self.disc_set = disc_set
            self.disc_model.splice(0, self.disc_model.get_n_items(), [entry.label for entry in disc_set.discs])
            index = next((i for i, entry in enumerate(disc_set.discs) if entry.image == selected), 0)
            self.disc_drop.set_selected(index)
            multi = disc_set.multidisc
            live_session = bool(self.active_bridge_cache and self.sandbox.running())
            self.disc_drop.set_sensitive(multi and not self.busy)
            self.live_multidisc_switch.set_sensitive(multi and not self.sandbox.running() and not self.busy)
            self.save_disc_set_btn.set_sensitive(not live_session and not self.busy)
            self.add_disc_to_set_btn.set_sensitive(not live_session and not self.busy)
            self.forget_disc_set_btn.set_sensitive(saved is not None and not live_session and not self.busy)
            if saved is not None:
                self.multidisc_status.set_text(
                    f'Set salvato: "{saved.name}" · {len(disc_set.discs)} supporti · ' 
                    "percorsi originali Redump/TOSEC preservati. "
                    "Live: cache host-side RO + un solo /dev/srX attivo per Wine."
                )
            elif multi:
                numbers = ", ".join(str(entry.number) for entry in disc_set.discs)
                self.multidisc_status.set_text(
                    f"Rilevamento automatico: {len(disc_set.discs)} supporti · dischi {numbers}. "
                    "Il rilevamento è solo un suggerimento: 'Crea set da questo disco' parte dal solo descriptor selezionato "
                    "e poi puoi aggiungere gli altri supporti esplicitamente, senza modificare i dump."
                )
            else:
                self.multidisc_status.set_text(
                    "Multidisco: nessun set salvato/correlato. Puoi salvare questo disco come nuovo set "
                    "e aggiungere gli altri descriptor dalle loro cartelle originali."
                )
        except Exception as exc:
            self.disc_set = None
            self.disc_model.splice(0, self.disc_model.get_n_items(), [])
            self.live_multidisc_switch.set_sensitive(False)
            self.forget_disc_set_btn.set_sensitive(False)
            self.multidisc_status.set_text(f"Multidisco: errore {exc}")
        return False

    def save_current_disc_set(self):
        selected = self.selected_image()
        existing = find_saved_set(selected, self.saved_disc_sets)
        if existing is None:
            # Persistenza archivistica esplicita: l'autodetection non viene mai
            # trasformata implicitamente in un set salvato. Si parte dal solo
            # descriptor selezionato (tipicamente Disc 1) e si aggiungono poi
            # gli altri supporti dai rispettivi percorsi originali.
            saved = make_new_saved_set(selected, RETROPC_ROOT)
        else:
            saved = make_saved_set(
                existing.name, [entry.image for entry in existing.discs], RETROPC_ROOT
            )
            saved = SavedDiscSet(existing.set_id, saved.name, saved.discs)
        self.saved_disc_sets = upsert_saved_set(self.saved_disc_sets, saved)
        path = save_saved_sets(self.saved_disc_sets, RETROPC_ROOT)
        GLib.idle_add(self.refresh_disc_set)
        return (
            f'Set "{saved.name}" salvato: {len(saved.discs)} supporti. ' 
            f"Metadati: {path}. Dump originali non modificati."
        )

    def choose_disc_for_saved_set(self):
        try:
            selected = self.selected_image()
        except Exception as exc:
            self.set_message(str(exc), True)
            return
        dialog = Gtk.FileChooserNative.new(
            "Aggiungi descriptor originale al set",
            self,
            Gtk.FileChooserAction.OPEN,
            "_Aggiungi",
            "_Annulla",
        )
        if RETROPC_ROOT.exists():
            dialog.set_current_folder(Gio.File.new_for_path(str(RETROPC_ROOT)))

        def response(dlg, response_id):
            try:
                if response_id != Gtk.ResponseType.ACCEPT:
                    return
                chosen_file = dlg.get_file()
                path = Path(chosen_file.get_path()).resolve(strict=True) if chosen_file and chosen_file.get_path() else None
                if path is None:
                    raise RuntimeError("Nessun file selezionato.")
                existing = find_saved_set(selected, self.saved_disc_sets)
                if existing is None:
                    base = make_saved_set(suggest_set_name(selected), [selected], RETROPC_ROOT)
                else:
                    base = existing
                paths = [d.image for d in base.discs]
                if path not in paths:
                    paths.append(path)
                rebuilt = make_saved_set(base.name, paths, RETROPC_ROOT)
                rebuilt = SavedDiscSet(base.set_id, rebuilt.name, rebuilt.discs)
                self.saved_disc_sets = upsert_saved_set(self.saved_disc_sets, rebuilt)
                cfg = save_saved_sets(self.saved_disc_sets, RETROPC_ROOT)
                self.refresh_images()
                self.set_message(
                    f'Disco aggiunto al set "{rebuilt.name}". Metadati: {cfg}. File originale non modificato.'
                )
            except Exception as exc:
                self.set_message(str(exc), True)
            finally:
                dlg.destroy()

        dialog.connect("response", response)
        dialog.show()

    def forget_current_disc_set(self):
        selected = self.selected_image()
        existing = find_saved_set(selected, self.saved_disc_sets)
        if existing is None:
            return "Nessun set salvato associato all'immagine selezionata."
        self.saved_disc_sets = [s for s in self.saved_disc_sets if s.set_id != existing.set_id]
        path = save_saved_sets(self.saved_disc_sets, RETROPC_ROOT)
        GLib.idle_add(self.refresh_disc_set)
        return (
            f'Set "{existing.name}" dimenticato ({path}). ' 
            "Nessun dump, CUE o directory originale è stato modificato."
        )

    def selected_disc_entry(self) -> DiscEntry:
        if self.disc_set is None or not self.disc_set.discs:
            raise RuntimeError("Nessun set multidisco disponibile.")
        idx = self.ui_get(self.disc_drop.get_selected)
        if idx == Gtk.INVALID_LIST_POSITION or idx >= len(self.disc_set.discs):
            idx = 0
        return self.disc_set.discs[idx]

    def _select_image_path(self, image: Path):
        for idx, candidate in enumerate(self.images):
            if candidate == image:
                self.image_drop.set_selected(idx)
                break
        self.refresh_disc_set()
        return False

    def refresh_devices(self):
        if not self.cdemu:
            self.devices = []
            self.device_model.splice(0, self.device_model.get_n_items(), [])
            self.cdemu_status.set_text("CDEmu: non connesso")
            return False
        old = self.device_drop.get_selected()
        try:
            self.devices = self.cdemu.devices()
            self.device_model.splice(0, self.device_model.get_n_items(), [d.title for d in self.devices])
            live_locked = bool(
                self.active_bridge_cache and self.sandbox.running() and self.active_bridge_device_index is not None
            )
            if self.devices:
                if live_locked:
                    active_pos = next(
                        (i for i, dev in enumerate(self.devices) if dev.index == self.active_bridge_device_index),
                        None,
                    )
                    if active_pos is None:
                        raise RuntimeError(
                            f"Device CDEmu live #{self.active_bridge_device_index} non più presente."
                        )
                    self.device_drop.set_selected(active_pos)
                else:
                    self.device_drop.set_selected(
                        min(old, len(self.devices) - 1) if old != Gtk.INVALID_LIST_POSITION else 0
                    )
            self.device_drop.set_sensitive(not live_locked)
            self.refresh_status()
        except Exception as exc:
            self.cdemu_status.set_text(f"CDEmu: errore {exc}")
        return False

    def selected_device(self) -> DeviceState:
        if not self.devices:
            raise RuntimeError("Nessun device CDEmu disponibile.")
        idx = self.ui_get(self.device_drop.get_selected)
        if idx == Gtk.INVALID_LIST_POSITION or idx >= len(self.devices):
            idx = 0
        return self.devices[idx]

    def selected_image(self) -> Path:
        if not self.images:
            raise RuntimeError(f"Nessuna immagine trovata sotto {RETROPC_ROOT}.")
        idx = self.ui_get(self.image_drop.get_selected)
        if idx == Gtk.INVALID_LIST_POSITION or idx >= len(self.images):
            idx = 0
        image = self.images[idx].resolve(strict=True)
        if not image.is_relative_to(RETROPC_ROOT.resolve(strict=False)):
            raise RuntimeError("Immagine fuori dalla directory retropc autorizzata.")
        return image

    def refresh_status(self):
        try:
            d = self.selected_device()
            media = ", ".join(Path(x).name for x in d.filenames) if d.filenames else "vuoto"
            self.cdemu_status.set_text(
                f"Device #{d.index}: {'caricato' if d.loaded else 'vuoto'} · {media} · sr={d.sr_path or '—'} · sg={d.sg_path or '—'}"
            )
            target, ro = self.mount_info(d.sr_path)
            self.mount_status.set_text(
                f"Mount: {target} · {'RO ✓' if ro else 'RW ⚠'}" if target else "Mount: non montato"
            )
        except Exception:
            self.cdemu_status.set_text("CDEmu: —")
            self.mount_status.set_text("Mount: —")
        return False

    def refresh_sandbox_status(self):
        try:
            audit = self.sandbox.audit()
            if audit.network_persistent:
                self.sandbox_status.set_text(f"Bubblejail {INSTANCE}: [network] permanente PRESENTE ⚠")
            else:
                self.sandbox_status.set_text(
                    f"Bubblejail {INSTANCE}: rete base OFF ✓ · runtime network {'ON' if self.network_switch.get_active() else 'OFF'}"
                )
            if audit.dangerous:
                self.fs_status.set_text("Filesystem BLOCCATO: " + ", ".join(audit.dangerous))
            else:
                rw = ", ".join(audit.rw) if audit.rw else "nessuna"
                ro = ", ".join(audit.ro) if audit.ro else "nessuna"
                self.fs_status.set_text(f"Whitelist: RW [{rw}] · RO [{ro}]")
        except Exception as exc:
            self.sandbox_status.set_text(f"Bubblejail: {exc}")
            self.fs_status.set_text("Filesystem: non verificato")
        return False


    @staticmethod
    def _clear_listbox(box: Gtk.ListBox):
        child = box.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            box.remove(child)
            child = nxt

    def _render_whitelist(self):
        self._clear_listbox(self.rw_listbox)
        self._clear_listbox(self.ro_listbox)
        for path in self.whitelist_rw:
            label = Gtk.Label(label=path, xalign=0, selectable=True)
            label.set_margin_top(4); label.set_margin_bottom(4); label.set_margin_start(6); label.set_margin_end(6)
            self.rw_listbox.append(label)
        for path in self.whitelist_ro:
            label = Gtk.Label(label=path, xalign=0, selectable=True)
            label.set_margin_top(4); label.set_margin_bottom(4); label.set_margin_start(6); label.set_margin_end(6)
            self.ro_listbox.append(label)
        self.whitelist_status.set_text(
            f"In modifica: {len(self.whitelist_rw)} RW · {len(self.whitelist_ro)} RO"
        )

    def reload_whitelist(self):
        try:
            audit = self.sandbox.audit()
            self.whitelist_rw = list(audit.rw)
            self.whitelist_ro = list(audit.ro)
            self._render_whitelist()
            if audit.dangerous:
                self.whitelist_status.set_text("Profilo attuale richiede attenzione: " + ", ".join(audit.dangerous))
        except Exception as exc:
            if hasattr(self, "whitelist_status"):
                self.whitelist_status.set_text(f"Impossibile leggere whitelist: {exc}")
        return False

    def choose_whitelist_folder(self, mode: str):
        dialog = Gtk.FileChooserNative.new(
            "Aggiungi directory alla whitelist",
            self,
            Gtk.FileChooserAction.SELECT_FOLDER,
            "_Aggiungi",
            "_Annulla",
        )
        if DATA_ROOT.exists():
            dialog.set_current_folder(Gio.File.new_for_path(str(DATA_ROOT)))

        def response(dlg, response_id):
            try:
                if response_id == Gtk.ResponseType.ACCEPT:
                    f = dlg.get_file()
                    path = f.get_path() if f else None
                    if path:
                        resolved = str(Path(path).resolve(strict=True))
                        target = self.whitelist_rw if mode == "rw" else self.whitelist_ro
                        other = self.whitelist_ro if mode == "rw" else self.whitelist_rw
                        if resolved in other:
                            self.set_message("La directory è già presente con permesso opposto.", True)
                        elif resolved not in target:
                            target.append(resolved)
                            target.sort(key=str.casefold)
                            self._render_whitelist()
            except Exception as exc:
                self.set_message(str(exc), True)
            finally:
                dlg.destroy()

        dialog.connect("response", response)
        dialog.show()

    def remove_whitelist_selected(self, mode: str):
        box = self.rw_listbox if mode == "rw" else self.ro_listbox
        values = self.whitelist_rw if mode == "rw" else self.whitelist_ro
        row = box.get_selected_row()
        if row is None:
            self.set_message("Seleziona prima una directory da rimuovere.", True)
            return
        idx = row.get_index()
        if 0 <= idx < len(values):
            values.pop(idx)
            self._render_whitelist()

    def apply_whitelist(self):
        rw, ro = self.ui_get(lambda: (list(self.whitelist_rw), list(self.whitelist_ro)))
        backup = self.sandbox.set_whitelist(rw, ro)
        audit = self.sandbox.audit()
        if audit.dangerous:
            raise RuntimeError("Audit post-salvataggio fallito: " + ", ".join(audit.dangerous))
        return f"Whitelist applicata. Backup: {backup}"

    def restore_whitelist_backup(self):
        self.sandbox.restore_backup()
        GLib.idle_add(self.reload_whitelist)
        return "Backup services.toml ripristinato."

    def copy_test_log(self, *_):
        start, end = self.test_buffer.get_bounds()
        text = self.test_buffer.get_text(start, end, True)
        self.get_clipboard().set(text)
        self.set_message("Log applicazione copiato negli appunti.")

    def raw_changed(self, *_):
        self.sg_switch.set_sensitive(self.raw_switch.get_active())
        if not self.raw_switch.get_active():
            self.sg_switch.set_active(False)

    def mount_info(self, sr_path: str) -> tuple[str | None, bool]:
        if not sr_path:
            return None, False
        result = run_cmd(["findmnt", "-nr", "-S", sr_path, "-o", "TARGET,OPTIONS"])
        if result.returncode != 0 or not result.stdout.strip():
            return None, False
        line = result.stdout.strip().splitlines()[0]
        parts = line.split(maxsplit=1)
        target = parts[0]
        opts = parts[1].split(",") if len(parts) > 1 else []
        return target, "ro" in opts

    def _udisks_object_path(self, sr_path: str) -> str:
        # /dev/sr1 -> /org/freedesktop/UDisks2/block_devices/sr1
        return "/org/freedesktop/UDisks2/block_devices/" + Path(sr_path).name

    def _udisks_has_filesystem(self, sr_path: str) -> bool:
        if not shutil.which("gdbus"):
            # Fall back to udisksctl info. Its output lists the interfaces attached
            # to the object on current UDisks2 releases.
            info = run_cmd(["udisksctl", "info", "-b", sr_path], timeout=5)
            return "org.freedesktop.UDisks2.Filesystem" in info.stdout
        probe = run_cmd([
            "gdbus", "introspect", "--system",
            "--dest", "org.freedesktop.UDisks2",
            "--object-path", self._udisks_object_path(sr_path),
        ], timeout=5)
        return probe.returncode == 0 and "org.freedesktop.UDisks2.Filesystem" in probe.stdout

    def wait_udisks_filesystem(self, sr_path: str, timeout: float = 15.0) -> tuple[bool, str]:
        """Wait until UDisks2 has attached its Filesystem interface.

        CDEmu DeviceLoad returning is not sufficient: VHBA/kernel media-change,
        udev probing and UDisks2 object updates are asynchronous.  A block object
        can therefore exist for /dev/srX while still not being mountable.
        """
        if shutil.which("udevadm"):
            run_cmd(["udevadm", "settle", "--timeout=5"], timeout=6)

        deadline = time.monotonic() + timeout
        last_diag = ""
        while time.monotonic() < deadline:
            if self._udisks_has_filesystem(sr_path):
                return True, last_diag

            diag = []
            if shutil.which("lsblk"):
                r = run_cmd(["lsblk", "-dn", "-o", "NAME,FSTYPE,LABEL,SIZE", sr_path], timeout=4)
                if r.stdout.strip():
                    diag.append("lsblk=" + r.stdout.strip())
            if shutil.which("blkid"):
                # A harmless read-only probe also helps distinguish an optical
                # data filesystem from media such as Audio CD.
                r = run_cmd(["blkid", "-p", "-o", "export", sr_path], timeout=4)
                if r.stdout.strip():
                    vals = ", ".join(x for x in r.stdout.splitlines() if x.startswith(("TYPE=", "LABEL=", "USAGE=")))
                    if vals:
                        diag.append("blkid=" + vals)
            last_diag = "; ".join(diag) or "filesystem non ancora identificato"
            time.sleep(0.35)

        return False, last_diag

    def ensure_ro_mount(self, sr_path: str) -> str:
        if not shutil.which("udisksctl"):
            raise RuntimeError("udisksctl non disponibile.")
        target, ro = self.mount_info(sr_path)
        if target and ro:
            return target
        if target:
            un = run_cmd(["udisksctl", "unmount", "-b", sr_path])
            if un.returncode != 0:
                raise RuntimeError(un.stdout.strip() or f"Impossibile smontare {target}")

        ready, diag = self.wait_udisks_filesystem(sr_path)
        if not ready:
            info = run_cmd(["udisksctl", "info", "-b", sr_path], timeout=5)
            raise RuntimeError(
                f"UDisks2 vede {sr_path} come block device ma dopo 15 s non "
                "ha creato l'interfaccia Filesystem.\n"
                f"Diagnostica: {diag}\n"
                f"udisksctl info:\n{info.stdout.strip()}\n"
                "Se blkid/lsblk non riportano TYPE/FSTYPE, il supporto potrebbe "
                "non contenere un filesystem montabile (es. Audio CD) oppure il "
                "media-change CDEmu non è ancora stato riconosciuto."
            )

        result = run_cmd(["udisksctl", "mount", "-b", sr_path, "-o", "ro"], timeout=20)
        target, ro = self.mount_info(sr_path)
        if not target:
            raise RuntimeError((result.stdout.strip() + "\n") + "UDisks2 non ha creato un mount filesystem.")
        if not ro:
            raise RuntimeError(f"{target} non risulta RO.")
        return target

    def unmount(self, sr_path: str):
        target, _ = self.mount_info(sr_path)
        if target:
            result = run_cmd(["udisksctl", "unmount", "-b", sr_path])
            if result.returncode != 0:
                raise RuntimeError(result.stdout.strip() or f"Impossibile smontare {target}")

    @staticmethod
    def raw_device_read_only(sr_path: str) -> bool | None:
        """Return the block-layer RO flag as diagnostics only.

        CDEmu/VHBA optical devices can legitimately report ``0`` here even when
        a normally loaded image is used as read-only media.  Therefore this value
        must never be used as the security gate for exposing a CDEmu /dev/srX.
        """
        if not sr_path:
            return None
        name = Path(sr_path).name
        for candidate in (Path("/sys/class/block") / name / "ro", Path("/sys/block") / name / "ro"):
            try:
                value = candidate.read_text(encoding="ascii").strip()
            except OSError:
                continue
            if value in {"0", "1"}:
                return value == "1"
        if shutil.which("blockdev"):
            result = run_cmd(["blockdev", "--getro", sr_path], timeout=5)
            value = result.stdout.strip()
            if result.returncode == 0 and value in {"0", "1"}:
                return value == "1"
        return None

    @staticmethod
    def validate_cdemu_optical_device(sr_path: str) -> str:
        """Validate that *sr_path* is an actual Linux optical block device.

        The path itself comes from CDEmu's DeviceGetMapping D-Bus method.  This
        adds local kernel/sysfs validation before Bubblejail is allowed to expose
        it to Wine.  SCSI peripheral type 5 is CD/DVD-ROM.
        """
        if not sr_path:
            raise RuntimeError("Mapping CDEmu /dev/srX assente.")
        path = Path(sr_path)
        name = path.name
        if path.parent != Path("/dev") or not name.startswith("sr") or not name[2:].isdigit():
            raise RuntimeError(f"Mapping CDEmu inatteso: {sr_path}")
        try:
            st = path.stat()
        except OSError as exc:
            raise RuntimeError(f"Device CDEmu non accessibile: {sr_path}: {exc}") from exc
        if not stat.S_ISBLK(st.st_mode):
            raise RuntimeError(f"Il mapping CDEmu non è un block device: {sr_path}")
        scsi_type = Path("/sys/class/block") / name / "device" / "type"
        try:
            value = scsi_type.read_text(encoding="ascii").strip()
        except OSError as exc:
            raise RuntimeError(f"Impossibile verificare il tipo ottico di {sr_path}: {exc}") from exc
        if value != "5":
            raise RuntimeError(f"{sr_path} non è un device ottico SCSI (type={value!r}).")
        return f"{sr_path} block optical SCSI type=5"

    def option_state(self) -> dict[str, bool]:
        return self.ui_get(lambda: {
            "dpm-emulation": self.dpm_switch.get_active(),
            "tr-emulation": self.tr_switch.get_active(),
            "bad-sector-emulation": self.bad_switch.get_active(),
            "dvd-report-css": self.css_switch.get_active(),
        })

    def apply_options(self, index: int, settings: dict[str, bool] | None = None):
        if not self.cdemu:
            raise RuntimeError("CDEmu non connesso.")
        settings = settings or self.option_state()
        for name, enabled in settings.items():
            self.cdemu.set_bool_option(index, name, enabled)

    def apply_options_selected(self):
        d = self.selected_device()
        self.apply_options(d.index)
        return f"Opzioni applicate a device #{d.index}."

    def _bridge_neutral_dir(self) -> Path:
        path = self.sandbox.private_home / ".cache" / "bottles-retro-cd" / "empty-disc"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _make_disc_bridge(self) -> DiscBridge:
        return DiscBridge(
            INSTANCE,
            private_home=self.sandbox.private_home,
            neutral_dir=self._bridge_neutral_dir(),
            media_root=Path("/run/media") / getpass.getuser(),
        )

    def _running_bridge(self, device_index: int) -> DiscBridge:
        if not self.sandbox.running():
            raise RuntimeError("Bubblejail/Bottles non risulta attivo.")
        bridge = self.active_bridge
        if bridge is None or not bridge.alive():
            self.active_bridge = None
            raise RuntimeError(
                "Bottles è attivo senza bridge multidisco. Chiudilo e riavvialo con "
                "'Cambio live mentre Bottles è aperto' abilitato."
            )
        if self.active_bridge_device_index != device_index:
            raise RuntimeError(
                f"Il bridge è associato al device CDEmu #{self.active_bridge_device_index}, "
                f"non al device #{device_index}."
            )
        return bridge

    @staticmethod
    def _disc_cache_key(image: Path) -> str:
        return str(image.resolve(strict=False))

    def _cleanup_disc_cache(
        self,
        cache: dict[str, tuple[int, str, str]],
        base_count: int | None,
    ) -> list[str]:
        """Unmount/unload cached media and remove appended CDEmu devices when safe.

        RemoveDevice always removes the last device. We therefore only remove
        devices when the current device count still exactly matches the suffix
        this controller created. If another CDEmu client changed the device list,
        cached devices are unloaded but left present rather than risking removal
        of somebody else's drive.
        """
        lines: list[str] = []
        if not self.cdemu or not cache:
            return lines

        entries = sorted(cache.values(), key=lambda item: item[0], reverse=True)
        safe_entries: list[tuple[int, str, str]] = []
        for index, sr, mount in entries:
            try:
                mapped_sr, _mapped_sg = self.cdemu.mapping(index)
            except Exception as exc:
                lines.append(f"mapping cache #{index} non verificabile: {exc}")
                continue
            if sr and mapped_sr != sr:
                lines.append(
                    f"cache #{index} non toccata: mapping cambiato {sr} → {mapped_sr}"
                )
                continue
            safe_entries.append((index, sr, mount))

        for index, sr, _mount in safe_entries:
            try:
                if sr:
                    self.unmount(sr)
            except Exception as exc:
                lines.append(f"unmount cache #{index}: {exc}")
            try:
                loaded, _files = self.cdemu.status(index)
                if loaded:
                    self.cdemu.unload(index)
                    self.cdemu.wait_loaded(index, False)
            except Exception as exc:
                lines.append(f"unload cache #{index}: {exc}")

        if len(safe_entries) != len(entries):
            lines.append("device cache non rimossi: uno o più mapping non sono più quelli creati dalla GUI")
            return lines
        if base_count is None:
            lines.append("device cache lasciati vuoti: base count sconosciuto")
            return lines

        expected = base_count + len(cache)
        current = self.cdemu.number_of_devices()
        expected_indices = list(range(base_count, expected))
        actual_indices = sorted(index for index, _sr, _mount in cache.values())
        if current != expected or actual_indices != expected_indices:
            lines.append(
                f"device cache lasciati vuoti per sicurezza: count={current}, atteso={expected}, "
                f"indici={actual_indices}"
            )
            return lines

        owned = {index: sr for index, sr, _mount in safe_entries}
        while owned:
            current = self.cdemu.number_of_devices()
            expected_current = base_count + len(owned)
            if current != expected_current:
                lines.append(
                    f"rimozione cache interrotta: count={current}, atteso={expected_current}"
                )
                break
            last_index = current - 1
            expected_sr = owned.get(last_index)
            if expected_sr is None:
                lines.append(
                    f"rimozione cache interrotta: last device #{last_index} non appartiene alla GUI"
                )
                break
            try:
                mapped_sr, _mapped_sg = self.cdemu.mapping(last_index)
            except Exception as exc:
                lines.append(f"rimozione cache interrotta: mapping #{last_index}: {exc}")
                break
            if expected_sr and mapped_sr != expected_sr:
                lines.append(
                    f"rimozione cache interrotta: mapping #{last_index} cambiato {expected_sr} → {mapped_sr}"
                )
                break

            previous = current
            self.cdemu.remove_last_device()
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                now = self.cdemu.number_of_devices()
                if now < previous:
                    owned.pop(last_index, None)
                    break
                time.sleep(0.1)
            else:
                lines.append("timeout rimuovendo un device cache")
                break
        return lines

    def _cleanup_inactive_live_session(self) -> list[str]:
        if not self.active_bridge_cache:
            return []
        if self.sandbox.running():
            return ["cleanup non eseguito: Bottles/Bubblejail è nuovamente attivo"]
        lines = self._cleanup_disc_cache(
            dict(self.active_bridge_cache), self.active_bridge_cache_base_count
        )
        if self.active_bridge is not None:
            self.active_bridge.stop()
        self.active_bridge = None
        self.active_bridge_device_index = None
        self.active_bridge_sr = ""
        self.active_bridge_cache = {}
        self.active_bridge_cache_base_count = None
        return lines

    def _prepare_disc_cache(
        self, disc_set: DiscSet
    ) -> tuple[dict[str, tuple[int, str, str]], int]:
        if not self.cdemu:
            raise RuntimeError("CDEmu non connesso.")
        if not disc_set.multidisc:
            raise RuntimeError("La cache live richiede un set multidisco.")

        base_count = self.cdemu.number_of_devices()
        cache: dict[str, tuple[int, str, str]] = {}
        try:
            for entry in disc_set.discs:
                index = self.cdemu.add_device()
                pending = f"__pending__:{index}"
                cache[pending] = (index, "", "")
                sr, _sg = self.cdemu.wait_mapping(index)
                cache[pending] = (index, sr, "")
                self.cdemu.load(index, entry.image)
                self.cdemu.wait_loaded(index, True)
                self.apply_options(index)
                self.validate_cdemu_optical_device(sr)
                mount = self.ensure_ro_mount(sr)
                target, ro = self.mount_info(sr)
                if not target or not ro or target != mount:
                    raise RuntimeError(
                        f"Cache Disco {entry.number}: mount RO non verificato per {sr}."
                    )
                del cache[pending]
                cache[self._disc_cache_key(entry.image)] = (index, sr, mount)
            if len(cache) != len(disc_set.discs):
                raise RuntimeError("Cache multidisco incompleta.")
            return cache, base_count
        except Exception:
            self._cleanup_disc_cache(cache, base_count)
            raise

    def _cache_mount_for(self, image: Path) -> str:
        item = self.active_bridge_cache.get(self._disc_cache_key(image))
        if item is None:
            raise RuntimeError(f"Il disco {image.name} non è presente nella cache live.")
        _index, sr, mount = item
        target, ro = self.mount_info(sr)
        if not target or not ro or target != mount:
            raise RuntimeError(
                f"Il mount cache per {image.name} non è più disponibile RO: {mount}."
            )
        return mount

    def _load_media(self, index: int, image: Path, *, mount_required: bool) -> tuple[str, str | None]:
        if not self.cdemu:
            raise RuntimeError("CDEmu non connesso.")
        self.cdemu.load(index, image)
        self.cdemu.wait_loaded(index, True)
        self.apply_options(index)
        sr, _sg = self.cdemu.wait_mapping(index)
        self.validate_cdemu_optical_device(sr)
        if mount_required:
            return sr, self.ensure_ro_mount(sr)
        return sr, None

    def swap_to_image(self, image: Path) -> str:
        if not self.cdemu:
            raise RuntimeError("CDEmu non connesso.")
        image = image.resolve(strict=True)
        if not image.is_relative_to(RETROPC_ROOT.resolve(strict=False)):
            raise RuntimeError("Immagine fuori dalla directory retropc autorizzata.")

        d = self.cdemu.device_state(self.selected_device().index)
        running = self.sandbox.running()
        if not running and self.active_bridge_cache:
            self._cleanup_inactive_live_session()
        bridge: DiscBridge | None = None
        old_image = Path(d.filenames[0]).resolve(strict=False) if d.loaded and d.filenames else None
        old_sr = d.sr_path
        udisks_on = self.ui_get(self.udisks_switch.get_active)
        mount_required = udisks_on
        old_cache_mount: str | None = None
        new_cache_mount: str | None = None

        if running:
            bridge = self._running_bridge(d.index)
            new_cache_mount = self._cache_mount_for(image)
            if old_image is not None:
                old_cache_mount = self._cache_mount_for(old_image)
            bridge.neutralize()

        try:
            if d.loaded:
                self.unmount(d.sr_path)
                self.cdemu.unload(d.index)
                self.cdemu.wait_loaded(d.index, False)

            sr, target = self._load_media(d.index, image, mount_required=mount_required)
            if running:
                if not self.active_bridge_sr:
                    self.active_bridge_sr = old_sr
                if sr != self.active_bridge_sr:
                    raise RuntimeError(
                        f"Il mapping CDEmu è cambiato durante lo swap: {self.active_bridge_sr} → {sr}. "
                        "La jail mantiene volutamente il solo device originale."
                    )
                if new_cache_mount is None:
                    raise RuntimeError("Mount cache del nuovo disco assente.")
                bridge.set_target(Path(new_cache_mount))

            GLib.idle_add(self._select_image_path, image)
            if target:
                return f"Disco cambiato: {image.name} · {sr} · mount RO {target}"
            return f"Disco cambiato: {image.name} · {sr} · UDisks2 OFF"
        except Exception as primary:
            rollback = ""
            try:
                current = self.cdemu.device_state(d.index)
                if current.loaded:
                    try:
                        self.unmount(current.sr_path)
                    except Exception:
                        pass
                    self.cdemu.unload(d.index)
                    self.cdemu.wait_loaded(d.index, False)
                if old_image is not None and old_image.exists():
                    restored_sr, restored_mount = self._load_media(
                        d.index, old_image, mount_required=mount_required
                    )
                    if running and bridge is not None:
                        if restored_sr != self.active_bridge_sr:
                            raise RuntimeError(
                                f"rollback mapping inatteso: {restored_sr} != {self.active_bridge_sr}"
                            )
                        if old_cache_mount:
                            bridge.set_target(Path(old_cache_mount))
                        else:
                            bridge.neutralize()
                    rollback = " Il disco precedente è stato ripristinato."
                elif running and bridge is not None:
                    bridge.neutralize()
            except Exception as restore_exc:
                rollback = f" Rollback non riuscito: {restore_exc}"
            raise RuntimeError(f"Cambio disco fallito: {primary}.{rollback}") from primary

    def load_selected_image(self):
        return self.swap_to_image(self.selected_image())

    def swap_selected_disc(self):
        return self.swap_to_image(self.selected_disc_entry().image)

    def swap_relative_disc(self, delta: int):
        if self.disc_set is None or len(self.disc_set.discs) < 2:
            raise RuntimeError("Nessun set multidisco rilevato.")
        idx = self.ui_get(self.disc_drop.get_selected)
        if idx == Gtk.INVALID_LIST_POSITION or idx >= len(self.disc_set.discs):
            idx = 0
        idx = (idx + delta) % len(self.disc_set.discs)
        return self.swap_to_image(self.disc_set.discs[idx].image)

    def eject_selected_device(self):
        if not self.cdemu:
            raise RuntimeError("CDEmu non connesso.")
        d = self.cdemu.device_state(self.selected_device().index)
        if self.sandbox.running():
            bridge = self._running_bridge(d.index)
            bridge.neutralize()
        elif self.active_bridge_cache:
            self._cleanup_inactive_live_session()
        self.unmount(d.sr_path)
        if d.loaded:
            self.cdemu.unload(d.index)
            self.cdemu.wait_loaded(d.index, False)
        return f"Device #{d.index} espulso."

    def runtime_bubblejail_args(
        self,
        d: DeviceState | None,
        mount: str | None,
        *,
        network_on: bool,
        expose_mount: bool,
        raw_on: bool,
        sg_on: bool,
        gpu: GPUInfo | None,
        bridge: DiscBridge | None = None,
    ) -> list[str]:
        args = ["/usr/bin/bubblejail", "run"]
        args += bubblewrap_gpu_args(gpu)
        if network_on:
            args += ["--debug-bwrap-args", "share-net"]
            resolv = Path("/etc/resolv.conf")
            try:
                actual = resolv.resolve(strict=True)
            except OSError:
                actual = resolv
            if actual != resolv:
                args += ["--debug-bwrap-args", "ro-bind", str(actual), str(actual)]
        if bridge is not None:
            args += bridge.bubblewrap_args()
        elif mount and expose_mount:
            args += [
                "--debug-bwrap-args", "dir", JAIL_CD_TARGET,
                "--debug-bwrap-args", "ro-bind", mount, JAIL_CD_TARGET,
            ]
        if d is not None and raw_on and d.sr_path:
            self.validate_cdemu_optical_device(d.sr_path)
            args += ["--debug-bwrap-args", "dev-bind", d.sr_path, d.sr_path]
            if sg_on and d.sg_path and Path(d.sg_path).exists():
                args += ["--debug-bwrap-args", "dev-bind", d.sg_path, d.sg_path]
        args += ["--", INSTANCE]
        return args

    def launch_bottles(self):
        self.sandbox.ensure_runtime_args_supported()
        stale = self._cleanup_inactive_live_session()
        if stale:
            GLib.idle_add(
                self.set_message,
                "Pulizia cache multidisco precedente: " + "; ".join(stale),
            )
        audit = self.sandbox.audit()
        if audit.network_persistent:
            raise RuntimeError(
                "Rimuovi [network] dal profilo: la GUI gestisce la rete solo per il singolo avvio."
            )
        if audit.dangerous:
            raise RuntimeError(
                "Condivisioni filesystem non ammesse: " + ", ".join(audit.dangerous)
            )
        if self.sandbox.running():
            raise RuntimeError(
                "L'istanza Bottles è già attiva. Chiudila completamente prima di "
                "cambiare rete o permessi CD."
            )

        network_on, udisks_on, expose_mount, raw_on, sg_on, live_multidisc_on = self.ui_get(lambda: (
            self.network_switch.get_active(),
            self.udisks_switch.get_active(),
            self.expose_mount_switch.get_active(),
            self.raw_switch.get_active(),
            self.sg_switch.get_active(),
            self.live_multidisc_switch.get_active(),
        ))

        d: DeviceState | None = None
        mount: str | None = None
        launch_set: DiscSet | None = None
        try:
            candidate = self.cdemu.device_state(self.selected_device().index) if self.cdemu else None
        except RuntimeError:
            candidate = None

        if candidate is not None and candidate.loaded:
            d = candidate
            self.apply_options(d.index)
            if d.filenames:
                active_image = Path(d.filenames[0]).resolve(strict=False)
                if live_multidisc_on:
                    saved = find_saved_set(active_image, self.saved_disc_sets)
                    if saved is None:
                        raise RuntimeError(
                            "Il multidisco live richiede un set esplicito salvato contenente il disco attivo. "
                            "L'autodetection non viene usata come policy runtime."
                        )
                    launch_set = saved.to_disc_set()
                else:
                    launch_set = resolve_disc_set(
                        active_image, self.images, RETROPC_ROOT, self.saved_disc_sets
                    )

            if udisks_on:
                if not d.sr_path:
                    raise RuntimeError("Il media è caricato ma il mapping /dev/srX non è pronto.")
                mount = self.ensure_ro_mount(d.sr_path)
            elif d.sr_path:
                target, ro = self.mount_info(d.sr_path)
                if target and not ro and expose_mount:
                    raise RuntimeError(f"Il mount {target} è RW.")
                mount = target if ro else None

        if live_multidisc_on and d is None:
            raise RuntimeError("Il multidisco live richiede un disco CDEmu attivo appartenente a un set salvato.")
        if live_multidisc_on and (launch_set is None or not launch_set.multidisc):
            raise RuntimeError("Il set salvato deve contenere almeno due supporti per il multidisco live.")
        live_multidisc = bool(live_multidisc_on)
        if live_multidisc and (not udisks_on or not expose_mount or not mount):
            raise RuntimeError(
                "Il multidisco live richiede UDisks2 RO e 'Esporre mount RO come /mnt/cdemu'."
            )

        bridge: DiscBridge | None = None
        cache: dict[str, tuple[int, str, str]] = {}
        cache_base_count: int | None = None
        if live_multidisc:
            cache, cache_base_count = self._prepare_disc_cache(launch_set)
            if not d.filenames:
                self._cleanup_disc_cache(cache, cache_base_count)
                raise RuntimeError("Immagine attiva non determinabile per il bridge multidisco.")
            current_image = Path(d.filenames[0]).resolve(strict=False)
            current_item = cache.get(self._disc_cache_key(current_image))
            if current_item is None:
                self._cleanup_disc_cache(cache, cache_base_count)
                raise RuntimeError(
                    f"Il disco attivo {current_image.name} non appartiene alla cache del set rilevato."
                )
            bridge = self._make_disc_bridge()
            bridge.start(
                Path(current_item[2]),
                [Path(item[2]) for item in cache.values()],
            )

        gpu = self.selected_gpu()
        effective_raw = raw_on or live_multidisc
        effective_sg = sg_on and raw_on
        try:
            args = self.runtime_bubblejail_args(
                d, mount, network_on=network_on, expose_mount=expose_mount, raw_on=effective_raw,
                sg_on=effective_sg, gpu=gpu, bridge=bridge,
            )

            log_dir = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))) / "bottles-retro-cd"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "bottles-launch.log"
            with log_path.open("ab") as log_fh:
                proc = subprocess.Popen(
                    args,
                    start_new_session=True,
                    stdout=log_fh,
                    stderr=subprocess.STDOUT,
                )
            time.sleep(0.35)
            if proc.poll() is not None:
                raise RuntimeError(
                    f"Bubblejail/Bottles è terminato subito con rc={proc.returncode}. "
                    f"Log: {log_path}"
                )
        except Exception:
            if bridge is not None:
                bridge.stop()
            if cache:
                self._cleanup_disc_cache(cache, cache_base_count)
            raise

        if bridge is not None and d is not None:
            self.active_bridge = bridge
            self.active_bridge_device_index = d.index
            self.active_bridge_sr = d.sr_path
            self.active_bridge_cache = cache
            self.active_bridge_cache_base_count = cache_base_count
            self.device_drop.set_sensitive(False)
            GLib.idle_add(self._ensure_live_poll)
        else:
            self.active_bridge = None
            self.active_bridge_device_index = None
            self.active_bridge_sr = ""
            self.active_bridge_cache = {}
            self.active_bridge_cache_base_count = None

        cd_state = (
            f"{d.sr_path}{' · ' + mount if mount else ''}"
            if d is not None
            else "nessun CD"
        )
        if live_multidisc:
            cd_state += f" · multidisco live · cache RO {len(cache)}/{len(launch_set.discs)}"
        gpu_state = gpu.label if gpu is not None else "Mesa default"
        return (
            f"Bottles avviato · GPU {gpu_state} · rete {'ON' if network_on else 'OFF'} · {cd_state} · "
            f"log={log_path}"
        )

    def run_cdemu_test(self):
        if not self.cdemu:
            raise RuntimeError("CDEmu non connesso.")
        image = self.selected_image()
        lines = [
            f"[INFO] daemon={self.cdemu.daemon_version()} libMirage={self.cdemu.library_version()} interface={self.cdemu.interface_version()}",
            f"[INFO] immagine={image}",
        ]
        udisks_on = self.ui_get(self.udisks_switch.get_active)
        before = self.cdemu.number_of_devices()
        temp_index: int | None = None
        sr = ""
        mounted = False
        try:
            temp_index = self.cdemu.add_device()
            lines.append(f"[PASS] drive temporaneo creato: #{temp_index} (device count {before}→{self.cdemu.number_of_devices()})")
            sr, sg = self.cdemu.wait_mapping(temp_index)
            lines.append(f"[PASS] mapping pronto: sr={sr} sg={sg or '—'}")
            self.cdemu.load(temp_index, image)
            loaded, files = self.cdemu.wait_loaded(temp_index, True)
            lines.append(f"[PASS] DeviceLoad via D-Bus: loaded={loaded} file={files[0] if files else '—'}")
            if shutil.which("udevadm"):
                run_cmd(["udevadm", "settle", "--timeout=5"], timeout=6)
            raw_desc = self.validate_cdemu_optical_device(sr)
            lines.append(f"[PASS] device raw CDEmu validato: {raw_desc}")
            raw_ro = self.raw_device_read_only(sr)
            state = "RO" if raw_ro is True else "RW" if raw_ro is False else "non verificabile"
            lines.append(f"[INFO] block-layer ro={state} (diagnostico; non è la policy RO del mount)")
            if shutil.which("lsblk"):
                pr = run_cmd(["lsblk", "-dn", "-o", "NAME,FSTYPE,LABEL,SIZE", sr], timeout=4)
                lines.append(f"[INFO] kernel/udev iniziale: {pr.stdout.strip() or 'nessun FSTYPE/LABEL'}")

            # Exercise the same advanced device-option API used by gCDEmu.
            for name in ("dpm-emulation", "tr-emulation", "bad-sector-emulation", "dvd-report-css"):
                original = bool(self.cdemu.get_option(temp_index, name))
                self.cdemu.set_bool_option(temp_index, name, not original)
                changed = bool(self.cdemu.get_option(temp_index, name))
                if changed != (not original):
                    raise RuntimeError(f"Opzione {name} non applicata")
                self.cdemu.set_bool_option(temp_index, name, original)
                lines.append(f"[PASS] opzione {name}: get/set/get")

            if udisks_on:
                target = self.ensure_ro_mount(sr)
                mounted = True
                target2, ro = self.mount_info(sr)
                if not target2 or not ro:
                    raise RuntimeError("Verifica mount RO fallita")
                lines.append(f"[PASS] UDisks2 mount read-only: {target2}")
                test_path = shlex.quote(target2 + "/.retro-cd-ro-test")
                test = run_cmd(["sh", "-c", f"touch {test_path} 2>/dev/null"])
                if test.returncode == 0:
                    run_cmd(["rm", "-f", target2 + "/.retro-cd-ro-test"])
                    raise RuntimeError("Il mount dichiarato RO ha permesso una scrittura")
                lines.append("[PASS] prova di scrittura sul mount: negata")
            else:
                lines.append("[SKIP] UDisks2 disattivato")
        finally:
            if temp_index is not None:
                try:
                    if sr and mounted:
                        self.unmount(sr)
                except Exception as exc:
                    lines.append(f"[WARN] cleanup unmount: {exc}")
                try:
                    loaded, _ = self.cdemu.status(temp_index)
                    if loaded:
                        self.cdemu.unload(temp_index)
                        self.cdemu.wait_loaded(temp_index, False)
                except Exception as exc:
                    lines.append(f"[WARN] cleanup unload: {exc}")
                try:
                    # AddDevice always appends; RemoveDevice removes the last device, matching gCDEmu's model.
                    if self.cdemu.number_of_devices() == before + 1:
                        self.cdemu.remove_last_device()
                        deadline = time.monotonic() + 5
                        while time.monotonic() < deadline and self.cdemu.number_of_devices() > before:
                            time.sleep(0.1)
                        if self.cdemu.number_of_devices() == before:
                            lines.append("[PASS] drive temporaneo rimosso; cleanup completo")
                        else:
                            lines.append("[WARN] drive temporaneo non rimosso entro timeout")
                    elif self.cdemu.number_of_devices() > before + 1:
                        lines.append("[WARN] device count cambiato da un altro client; non rimuovo il last device per sicurezza")
                except Exception as exc:
                    lines.append(f"[WARN] cleanup RemoveDevice: {exc}")
        return "\n".join(lines)

    def run_sandbox_test(self):
        test_network = self.ui_get(self.test_network_check.get_active)
        results = self.sandbox.test()
        if test_network:
            results += self.sandbox.test_runtime_network()
        lines = []
        for state, name, detail in results:
            lines.append(f"[{state}] {name}: {detail}")
        passed = sum(1 for s, _, _ in results if s == "PASS")
        failed = sum(1 for s, _, _ in results if s == "FAIL")
        warned = sum(1 for s, _, _ in results if s == "WARN")
        lines.append(f"\nRisultato sandbox: PASS={passed} FAIL={failed} WARN={warned}")
        return "\n".join(lines)

    def run_integration_test(self):
        if not self.cdemu:
            raise RuntimeError("CDEmu non connesso.")
        self.sandbox.ensure_runtime_args_supported()
        audit = self.sandbox.audit()
        if audit.network_persistent or audit.dangerous:
            raise RuntimeError("Profilo Bubblejail non sicuro: correggere prima whitelist/rete persistente.")
        if self.sandbox.running():
            raise RuntimeError("Istanza Bottles già attiva; chiuderla prima del test integrato.")
        image = self.selected_image()
        udisks_on, sg_on = self.ui_get(lambda: (
            self.udisks_switch.get_active(), self.sg_switch.get_active()
        ))
        lines = [f"[INFO] test integrato con {image.name}"]
        before = self.cdemu.number_of_devices()
        temp = None
        sr = sg = ""
        mount = None
        try:
            temp = self.cdemu.add_device()
            sr, sg = self.cdemu.wait_mapping(temp)
            self.cdemu.load(temp, image)
            self.cdemu.wait_loaded(temp, True)
            lines.append(f"[PASS] CDEmu temp #{temp}: {sr} {sg or ''}".rstrip())
            raw_desc = self.validate_cdemu_optical_device(sr)
            lines.append(f"[PASS] device raw CDEmu validato: {raw_desc}")
            raw_ro = self.raw_device_read_only(sr)
            state = "RO" if raw_ro is True else "RW" if raw_ro is False else "non verificabile"
            lines.append(f"[INFO] block-layer ro={state} (diagnostico; mount RO verificato separatamente)")
            if udisks_on:
                mount = self.ensure_ro_mount(sr)
                lines.append(f"[PASS] mount host RO: {mount}")

            args = ["bubblejail", "run"]
            if mount:
                args += [
                    "--debug-bwrap-args", "dir", JAIL_CD_TARGET,
                    "--debug-bwrap-args", "ro-bind", mount, JAIL_CD_TARGET,
                ]
            args += ["--debug-bwrap-args", "dev-bind", sr, sr]
            if sg_on and sg and Path(sg).exists():
                args += ["--debug-bwrap-args", "dev-bind", sg, sg]
            args += ["--debug-shell", INSTANCE]
            q = shlex.quote
            script = f"""
set +e
[ -b {q(sr)} ]; printf 'I_SR=%s\n' "$?"
[ -e {q(str(DATA_ROOT / 'progetti'))} ]; printf 'I_PROGETTI=%s\n' "$?"
[ -e {q(str(DATA_ROOT / 'SteamLibrary'))} ]; printf 'I_STEAM=%s\n' "$?"
"""
            if mount:
                script += f"""
[ -d {q(JAIL_CD_TARGET)} ]; printf 'I_MOUNT=%s\n' "$?"
touch {q(JAIL_CD_TARGET + '/.integration-write-test')} 2>/dev/null; printf 'I_WRITE=%s\n' "$?"
rm -f {q(JAIL_CD_TARGET + '/.integration-write-test')} 2>/dev/null
"""
            script += "exit\n"
            proc = run_cmd(args, input_text=script, timeout=40)
            vals = {}
            for line in proc.stdout.splitlines():
                if line.startswith("I_") and "=" in line:
                    k, v = line.split("=", 1)
                    vals[k] = v.strip()
            checks = [
                (vals.get("I_SR") == "0", "device raw /dev/srX visibile"),
                (vals.get("I_PROGETTI") != "0", "Data/progetti nascosta"),
                (vals.get("I_STEAM") != "0", "Data/SteamLibrary nascosta"),
            ]
            if mount:
                checks += [
                    (vals.get("I_MOUNT") == "0", "/mnt/cdemu visibile"),
                    (vals.get("I_WRITE") != "0", "/mnt/cdemu read-only"),
                ]
            for ok, label in checks:
                lines.append(f"[{'PASS' if ok else 'FAIL'}] {label}")
            if not all(ok for ok, _ in checks):
                raise RuntimeError("Uno o più controlli di integrazione Bubblejail sono falliti.\n" + "\n".join(lines))
        finally:
            if temp is not None:
                try:
                    if mount and sr:
                        self.unmount(sr)
                except Exception as exc:
                    lines.append(f"[WARN] cleanup unmount: {exc}")
                try:
                    loaded, _ = self.cdemu.status(temp)
                    if loaded:
                        self.cdemu.unload(temp)
                        self.cdemu.wait_loaded(temp, False)
                except Exception as exc:
                    lines.append(f"[WARN] cleanup unload: {exc}")
                try:
                    if self.cdemu.number_of_devices() == before + 1:
                        self.cdemu.remove_last_device()
                        deadline = time.monotonic() + 5
                        while time.monotonic() < deadline and self.cdemu.number_of_devices() > before:
                            time.sleep(0.1)
                        lines.append("[PASS] cleanup drive temporaneo" if self.cdemu.number_of_devices() == before else "[WARN] cleanup device timeout")
                except Exception as exc:
                    lines.append(f"[WARN] cleanup RemoveDevice: {exc}")
        return "\n".join(lines)

    def run_disc_cache_test(self):
        if not self.cdemu:
            raise RuntimeError("CDEmu non connesso.")
        if self.sandbox.running():
            raise RuntimeError("Chiudi Bottles/Bubblejail prima del test cache multidisco.")

        image = self.selected_image()
        disc_set = resolve_disc_set(
            image, self.images, RETROPC_ROOT, self.saved_disc_sets
        )
        if not disc_set.multidisc:
            raise RuntimeError(f"Nessun set multidisco rilevato per {image.name}.")

        lines = [
            f"[INFO] set multidisco: {len(disc_set.discs)} supporti",
            "[INFO] " + ", ".join(f"Disc {entry.number}={entry.image.name}" for entry in disc_set.discs),
        ]
        cache: dict[str, tuple[int, str, str]] = {}
        base_count: int | None = None
        bridge: DiscBridge | None = None
        try:
            cache, base_count = self._prepare_disc_cache(disc_set)
            if len(cache) != len(disc_set.discs):
                raise RuntimeError(
                    f"Cache incompleta: {len(cache)}/{len(disc_set.discs)} supporti."
                )
            mounts: list[Path] = []
            for entry in disc_set.discs:
                item = cache.get(self._disc_cache_key(entry.image))
                if item is None:
                    raise RuntimeError(f"Disco {entry.number} assente dalla cache.")
                index, sr, mount = item
                target, ro = self.mount_info(sr)
                if target != mount or not ro:
                    raise RuntimeError(f"Disco {entry.number}: mount cache non più RO.")
                mounts.append(Path(mount))
                lines.append(
                    f"[PASS] Disco {entry.number}: cache device #{index} · {sr} · mount RO {mount}"
                )

            if len({str(m) for m in mounts}) != len(mounts):
                raise RuntimeError("I mount cache non sono distinti.")
            lines.append(f"[PASS] mount cache distinti: {len(mounts)}")

            first = cache[self._disc_cache_key(disc_set.discs[0].image)]
            bridge = self._make_disc_bridge()
            bridge.start(Path(first[2]), mounts)
            status = bridge.status()
            expected_targets = len(mounts) + 1  # + neutral
            if status["targets"] != expected_targets:
                raise RuntimeError(
                    f"Bridge cache registra {status['targets']} target, attesi {expected_targets}."
                )
            lines.append(
                f"[PASS] bridge registra tutti i mount cache: targets={status['targets']}"
            )
        finally:
            if bridge is not None:
                bridge.stop()
            if cache:
                warnings = self._cleanup_disc_cache(cache, base_count)
                if warnings:
                    lines.extend(f"[WARN] cleanup: {warning}" for warning in warnings)
                else:
                    lines.append("[PASS] cleanup cache multidisco completo")

        return "\n".join(lines)

    def run_disc_bridge_test(self):
        self.sandbox.ensure_runtime_args_supported()
        if self.sandbox.running():
            raise RuntimeError("Chiudi Bottles/Bubblejail prima del test bridge multidisco.")

        root = self.sandbox.private_home / ".cache" / "bottles-retro-cd" / "bridge-selftest"
        a = root / "disc-a"
        b = root / "disc-b"
        neutral = root / "neutral"
        shutil.rmtree(root, ignore_errors=True)
        a.mkdir(parents=True, exist_ok=True)
        b.mkdir(parents=True, exist_ok=True)
        neutral.mkdir(parents=True, exist_ok=True)
        (a / "marker.txt").write_text("A\n", encoding="ascii")
        (b / "marker.txt").write_text("B\n", encoding="ascii")

        bridge = DiscBridge(
            INSTANCE,
            private_home=self.sandbox.private_home,
            neutral_dir=neutral,
            media_root=root,
        )
        proc = None
        lines = []
        try:
            bridge.start(a, [a, b])
            status = bridge.status()
            lines.append(
                f"[PASS] bridge statico preparato: target={Path(status['target']).name} "
                f"targets={status['targets']}"
            )
            args = ["bubblejail", "run"] + bridge.bubblewrap_args() + ["--debug-shell", INSTANCE]
            proc = subprocess.Popen(
                args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if proc.stdin is None or proc.stdout is None:
                raise RuntimeError("Pipe del test bridge non disponibili")
            proc.stdin.write(
                "printf 'BRIDGE_FIRST='; cat /mnt/cdemu/marker.txt 2>&1\n"
                "sleep 3\n"
                "printf 'BRIDGE_SECOND='; cat /mnt/cdemu/marker.txt 2>&1\n"
                "exit\n"
            )
            proc.stdin.flush()
            time.sleep(1.0)
            bridge.set_target(b)
            lines.append("[PASS] selector privato cambiato A → B mentre la jail è attiva")
            proc.stdin.close()
            output = proc.stdout.read()
            rc = proc.wait(timeout=15)
            if rc != 0:
                raise RuntimeError(f"Debug shell bridge rc={rc}:\n{output[-3000:]}")
            if "BRIDGE_FIRST=A" not in output:
                raise RuntimeError("La jail non ha letto il target iniziale A.\n" + output[-3000:])
            lines.append("[PASS] /mnt/cdemu iniziale legge A")
            if "BRIDGE_SECOND=B" not in output:
                raise RuntimeError("La stessa jail non ha seguito il target B.\n" + output[-3000:])
            lines.append("[PASS] /mnt/cdemu segue B senza riavviare Bubblejail")
            return "\n".join(lines)
        finally:
            if proc is not None and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
            bridge.stop()
            shutil.rmtree(root, ignore_errors=True)

    def run_all_tests(self):
        c = self.run_cdemu_test()
        s = self.run_sandbox_test()
        i = self.run_integration_test()
        b = self.run_disc_bridge_test()
        sep = "\n\n" + ("=" * 72) + "\n\n"
        return c + sep + s + sep + i + sep + b


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)

    def do_activate(self):
        win = self.props.active_window
        if not win:
            win = Window(self)
        win.present()


if __name__ == "__main__":
    raise SystemExit(App().run())
