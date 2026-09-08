#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

DGVOODOO_GUI = Path(__file__).with_name("bottles-retro-cd-gui-dgvoodoo.py")
_spec = importlib.util.spec_from_file_location("_bottles_retro_cd_dgvoodoo", DGVOODOO_GUI)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Impossibile caricare la GUI dgVoodoo2 RetroCD: {DGVOODOO_GUI}")
_dg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dg)

Gtk = _dg.Gtk


class Window(_dg.Window):
    """Final GUI composition layer: keep the long dgVoodoo2 page scrollable."""

    def __init__(self, app):
        super().__init__(app)
        self._make_dgvoodoo_tab_scrollable()

    def _make_dgvoodoo_tab_scrollable(self) -> None:
        """Wrap only the dgVoodoo2 notebook page in a vertical scroller.

        The Point-7 page intentionally contains detailed per-wrapper controls and
        security/status text.  On shorter displays the action row can otherwise
        fall below the visible notebook allocation.  Reparenting only this page
        avoids shrinking labels or changing the validated tabs from Points 1-6.
        """
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


# Keep the existing dynamic App wiring used by the layered RetroCD GUI.
_dg._life._ext._base.Window = Window
App = _dg.App

if __name__ == "__main__":
    raise SystemExit(App().run())
