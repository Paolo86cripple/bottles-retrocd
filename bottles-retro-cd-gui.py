#!/usr/bin/env python3
from __future__ import annotations

import getpass
import os
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gio, GLib, Gtk

from cdemu_backend import CDEmuBackend, DeviceState
from sandbox_backend import (
    DATA_ROOT,
    EGLLIBRARY_ROOT,
    INSTANCE,
    RETROPC_ROOT,
    SandboxBackend,
    run_cmd,
)

APP_ID = "org.local.BottlesRetroCD"
APP_NAME = "Bottles Retro CD"
VERSION = "0.4.0-rc1"
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
        self.busy = False
        self._ui_thread_id = threading.get_ident()

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
            "Consente a Wine di interrogare il lettore CDEmu come dispositivo ottico.",
            True,
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
                "Questi test non installano nulla e non avviano giochi. Il test CDEmu crea un drive temporaneo, "
                "lo usa e lo rimuove; il test sandbox apre solo una debug shell Bubblejail automatizzata. "
                "Il pulsante Avvia Bottles nel tab Sandbox è invece un test operativo esplicito."
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
        self.test_buffer.set_text("Nessun test eseguito.\n")

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
        self.refresh_all()
        return False

    def set_message(self, text: str, error: bool = False):
        self.message.set_text(text)
        if error:
            self.message.add_css_class("error")
        else:
            self.message.remove_css_class("error")

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
            self.test_cdemu_btn, self.test_sandbox_btn, self.test_integration_btn, self.test_all_btn,
        ):
            widget.set_sensitive(not busy)

    def background(self, fn, report: bool = False):
        if self.busy:
            return
        self.set_busy(True)
        if report:
            self.test_buffer.set_text("Test in esecuzione…\n")

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
            self.set_message(error, True)
            if report:
                self.test_buffer.set_text(f"FAIL: {error}\n")
        else:
            self.set_message(str(value or "Operazione completata."))
            if report:
                self.test_buffer.set_text(str(value) + ("\n" if value and not str(value).endswith("\n") else ""))
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
            if self.devices:
                self.device_drop.set_selected(min(old, len(self.devices) - 1) if old != Gtk.INVALID_LIST_POSITION else 0)
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
        self.get_clipboard().set_text(text)
        self.set_message("Log dei test copiato negli appunti.")

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
        """Return the kernel read-only state for a block device, when knowable."""
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

    def wait_raw_device_read_only(self, sr_path: str, timeout: float = 5.0) -> bool | None:
        deadline = time.monotonic() + timeout
        last: bool | None = None
        while time.monotonic() < deadline:
            last = self.raw_device_read_only(sr_path)
            if last is True:
                return True
            time.sleep(0.2)
        return last

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

    def load_selected_image(self):
        if not self.cdemu:
            raise RuntimeError("CDEmu non connesso.")
        d = self.selected_device()
        if d.loaded:
            self.unmount(d.sr_path)
            self.cdemu.unload(d.index)
            self.cdemu.wait_loaded(d.index, False)
        image = self.selected_image()
        self.cdemu.load(d.index, image)
        self.cdemu.wait_loaded(d.index, True)
        self.apply_options(d.index)
        sr, _sg = self.cdemu.wait_mapping(d.index)
        udisks_on = self.ui_get(self.udisks_switch.get_active)
        if udisks_on:
            target = self.ensure_ro_mount(sr)
            return f"Caricata {image.name}; mount RO: {target}"
        return f"Caricata {image.name}; UDisks2 OFF."

    def eject_selected_device(self):
        if not self.cdemu:
            raise RuntimeError("CDEmu non connesso.")
        d = self.selected_device()
        self.unmount(d.sr_path)
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
    ) -> list[str]:
        args = ["/usr/bin/bubblejail", "run"]
        if network_on:
            args += ["--debug-bwrap-args", "share-net"]
            resolv = Path("/etc/resolv.conf")
            try:
                actual = resolv.resolve(strict=True)
            except OSError:
                actual = resolv
            if actual != resolv:
                args += ["--debug-bwrap-args", "ro-bind", str(actual), str(actual)]
        if mount and expose_mount:
            args += [
                "--debug-bwrap-args", "dir", JAIL_CD_TARGET,
                "--debug-bwrap-args", "ro-bind", mount, JAIL_CD_TARGET,
            ]
        if d is not None and raw_on and d.sr_path:
            raw_ro = self.wait_raw_device_read_only(d.sr_path)
            if raw_ro is not True:
                state = "RW" if raw_ro is False else "non verificabile"
                raise RuntimeError(
                    f"Rifiuto esposizione raw di {d.sr_path}: stato kernel {state}. "
                    "Per questo profilo il device ottico deve risultare read-only."
                )
            args += ["--debug-bwrap-args", "dev-bind", d.sr_path, d.sr_path]
            if sg_on and d.sg_path and Path(d.sg_path).exists():
                args += ["--debug-bwrap-args", "dev-bind", d.sg_path, d.sg_path]
        args += ["--", INSTANCE]
        return args

    def launch_bottles(self):
        self.sandbox.ensure_runtime_args_supported()
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

        network_on, udisks_on, expose_mount, raw_on, sg_on = self.ui_get(lambda: (
            self.network_switch.get_active(),
            self.udisks_switch.get_active(),
            self.expose_mount_switch.get_active(),
            self.raw_switch.get_active(),
            self.sg_switch.get_active(),
        ))

        # Il CD è opzionale. Questo permette, per esempio, di aprire Bottles con
        # rete temporanea ON per scaricare un runner senza concedere device ottici.
        d: DeviceState | None = None
        mount: str | None = None
        try:
            candidate = self.selected_device()
        except RuntimeError:
            candidate = None

        if candidate is not None and candidate.loaded:
            d = candidate
            self.apply_options(d.index)

            if udisks_on:
                if not d.sr_path:
                    raise RuntimeError("Il media è caricato ma il mapping /dev/srX non è pronto.")
                mount = self.ensure_ro_mount(d.sr_path)
            elif d.sr_path:
                target, ro = self.mount_info(d.sr_path)
                if target and not ro and expose_mount:
                    raise RuntimeError(f"Il mount {target} è RW.")
                mount = target if ro else None

        args = self.runtime_bubblejail_args(
            d, mount, network_on=network_on, expose_mount=expose_mount, raw_on=raw_on, sg_on=sg_on
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

        cd_state = (
            f"{d.sr_path}{' · ' + mount if mount else ''}"
            if d is not None
            else "nessun CD"
        )
        return (
            f"Bottles avviato · rete {'ON' if network_on else 'OFF'} · {cd_state} · "
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
            raw_ro = self.wait_raw_device_read_only(sr)
            if raw_ro is True:
                lines.append(f"[PASS] device raw kernel read-only: {sr}")
            elif raw_ro is False:
                raise RuntimeError(f"Il device raw {sr} risulta RW al kernel")
            else:
                raise RuntimeError(f"Stato read-only raw non verificabile per {sr}")
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
            raw_ro = self.wait_raw_device_read_only(sr)
            if raw_ro is not True:
                raise RuntimeError(f"Device raw {sr} non verificato read-only (stato={raw_ro})")
            lines.append(f"[PASS] device raw kernel read-only: {sr}")
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

    def run_all_tests(self):
        c = self.run_cdemu_test()
        s = self.run_sandbox_test()
        i = self.run_integration_test()
        sep = "\n\n" + ("=" * 72) + "\n\n"
        return c + sep + s + sep + i


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
