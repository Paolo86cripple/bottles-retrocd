#!/usr/bin/env python3
"""Bottles Retro CD GUI entrypoint with verifier extension.

The validated rc2/multidisc controller is kept byte-identical in
``bottles-retro-cd-gui-base.py``.  This entrypoint subclasses it to add the
Redump/TOSEC verifier and the reviewed log-clear action without rewriting the
security-sensitive CDEmu/Bubblejail/GPU code.
"""
from __future__ import annotations

import importlib.util
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

from protection_scanner import (  # noqa: E402
    compare_catalog_protection,
    format_scan,
    scan_image,
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
            # Fail visibly rather than silently losing a reviewed control if the
            # base layout changes in a future release.
            raise RuntimeError("Layout Test inatteso: impossibile inserire 'Pulisci log'.")

    def _clear_log(self, *_):
        if self.busy:
            return
        self.test_buffer.set_text("")
        # Do not call set_message(): it appends to the log and would immediately
        # repopulate the buffer that the user explicitly asked to clear.
        self.message.set_text("Log applicazione pulito.")
        self.message.remove_css_class("error")

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
                # Imported material is intentionally kept in a separate source
                # namespace; official Redump/TOSEC updates cannot overwrite it.
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


# App.do_activate performs a global lookup of Window in the base module. Replace
# that global with the reviewed extension before running the unchanged App class.
_base.Window = Window
App = _base.App

if __name__ == "__main__":
    raise SystemExit(App().run())
