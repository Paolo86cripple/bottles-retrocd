#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

LIFECYCLE_GUI = Path(__file__).with_name("bottles-retro-cd-gui-lifecycle.py")
_spec = importlib.util.spec_from_file_location("_bottles_retro_cd_lifecycle", LIFECYCLE_GUI)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Impossibile caricare la GUI lifecycle RetroCD: {LIFECYCLE_GUI}")
_life = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_life)

Gtk = _life.Gtk
GLib = _life.GLib
Gio = _life._ext.Gio

from bottles_storage import discover_bottles  # noqa: E402
from dgvoodoo_backend import (  # noqa: E402
    BottleInfo,
    DgVoodooError,
    ReleaseInfo,
    Wrapper,
    download_release,
    fetch_latest_release,
    manager_cache_dir,
    sha256_file,
    install_wrappers,
    uninstall_wrappers,
    validate_game_target,
    wine_override_names,
    wine_overrides_value,
)
from dgvoodoo_state import InstallationState, inspect_installation  # noqa: E402
from dgvoodoo_policy import (  # noqa: E402
    activate_app_overrides,
    activation_status,
    deactivate_app_overrides,
    query_app_override,
)
from sandbox_backend import INSTANCE  # noqa: E402


WRAPPER_UI = (
    (Wrapper.DDRAW, "DirectDraw", "DDraw.dll · DirectDraw e Direct3D 1–7 via il wrapper Microsoft di dgVoodoo2."),
    (Wrapper.D3DIMM, "Direct3D Immediate Mode", "D3DImm.dll · wrapper D3D legacy separato, solo se richiesto dal titolo."),
    (Wrapper.D3DIM700, "Direct3D 7 Immediate Mode", "D3DIM700.dll · wrapper D3D7 legacy, selezione esplicita."),
    (Wrapper.D3D8, "Direct3D 8", "D3D8.dll · wrapper D3D8 di dgVoodoo2."),
    (Wrapper.D3D9, "Direct3D 9", "D3D9.dll · wrapper D3D9 di dgVoodoo2."),
    (Wrapper.GLIDE, "3Dfx Glide", "Glide.dll · compatibilità Glide 1.x."),
    (Wrapper.GLIDE2X, "3Dfx Glide 2", "Glide2x.dll · compatibilità Glide 2.x."),
    (Wrapper.GLIDE3X, "3Dfx Glide 3", "Glide3x.dll standard."),
    (Wrapper.GLIDE3X_NAPALM, "3Dfx Glide 3 Napalm", "Glide3x.dll alternativo dalla directory Napalm; incompatibile con Glide 3 standard."),
)


class Window(_life.Window):
    """Final Point-7 GUI layer; no changes to the validated launch/sandbox path."""

    def __init__(self, app):
        super().__init__(app)
        self._dg_storage = None
        self._dg_bottles: tuple[BottleInfo, ...] = ()
        self._dg_target: Path | None = None
        self._dg_latest_release: ReleaseInfo | None = None
        self._dg_syncing_wrappers = False
        self.build_dgvoodoo_tab()
        self.refresh_dgvoodoo_bottles()
        self.refresh_dgvoodoo_local_status()

    def build_dgvoodoo_tab(self):
        page = self.page_box()
        self.add_tab(page, "dgVoodoo2")

        intro = Gtk.Label(
            label=(
                "dgVoodoo2 è un layer di compatibilità opzionale per singolo executable. RetroCD scarica solo "
                "la release runtime ufficiale su richiesta esplicita, verifica il SHA-256 pubblicato da GitHub "
                "e non installa DLL globalmente. Wine/Proton non sono target supportati dall'upstream: usa questa "
                "funzione solo per titoli che ne hanno realmente bisogno."
            ),
            xalign=0,
            wrap=True,
        )
        intro.add_css_class("dim-label")
        page.append(intro)

        target_frame = Gtk.Frame(label="Target per-game")
        page.append(target_frame)
        target_box = self.frame_box(target_frame)
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        target_box.append(grid)

        grid.attach(Gtk.Label(label="Bottle", xalign=0), 0, 0, 1, 1)
        self.dg_bottle_model = Gtk.StringList.new([])
        self.dg_bottle_drop = Gtk.DropDown(model=self.dg_bottle_model, hexpand=True)
        self.dg_bottle_drop.connect("notify::selected", self._dg_bottle_changed)
        grid.attach(self.dg_bottle_drop, 1, 0, 1, 1)
        self.dg_bottle_refresh_btn = Gtk.Button(label="Aggiorna")
        self.dg_bottle_refresh_btn.connect("clicked", lambda *_: self.refresh_dgvoodoo_bottles())
        grid.attach(self.dg_bottle_refresh_btn, 2, 0, 1, 1)

        grid.attach(Gtk.Label(label="Executable", xalign=0), 0, 1, 1, 1)
        self.dg_exe_entry = Gtk.Entry(hexpand=True)
        self.dg_exe_entry.set_editable(False)
        self.dg_exe_entry.set_placeholder_text("Seleziona un .exe dentro drive_c della bottle")
        grid.attach(self.dg_exe_entry, 1, 1, 1, 1)
        self.dg_exe_btn = Gtk.Button(label="Scegli…")
        self.dg_exe_btn.connect("clicked", lambda *_: self.choose_dgvoodoo_executable())
        grid.attach(self.dg_exe_btn, 2, 1, 1, 1)

        self.dg_target_status = Gtk.Label(
            label="Target: nessun executable selezionato",
            xalign=0,
            wrap=True,
            selectable=True,
        )
        target_box.append(self.dg_target_status)

        wrappers_frame = Gtk.Frame(label="Wrapper espliciti")
        page.append(wrappers_frame)
        wrappers_box = self.frame_box(wrappers_frame)
        self.dg_wrapper_switches: dict[Wrapper, object] = {}
        for wrapper, title, description in WRAPPER_UI:
            switch = self.switch_row(wrappers_box, title, description, False)
            switch.connect("notify::active", self._dg_wrapper_changed, wrapper)
            self.dg_wrapper_switches[wrapper] = switch

        self.dg_override_preview = Gtk.Label(
            label="Wine AppDefaults preview: seleziona almeno un wrapper",
            xalign=0,
            wrap=True,
            selectable=True,
        )
        self.dg_override_preview.add_css_class("dim-label")
        wrappers_box.append(self.dg_override_preview)

        status_frame = Gtk.Frame(label="Release, cache e integrità")
        page.append(status_frame)
        status_box = self.frame_box(status_frame)
        self.dg_release_status = Gtk.Label(
            label="Release ufficiale: non verificata in questa sessione",
            xalign=0,
            wrap=True,
            selectable=True,
        )
        status_box.append(self.dg_release_status)
        self.dg_install_status = Gtk.Label(
            label="Payload: seleziona un executable",
            xalign=0,
            wrap=True,
            selectable=True,
        )
        status_box.append(self.dg_install_status)
        self.dg_activation_status = Gtk.Label(
            label="Wine AppDefaults: seleziona un executable",
            xalign=0,
            wrap=True,
            selectable=True,
        )
        status_box.append(self.dg_activation_status)

        status_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        status_box.append(status_row)
        self.dg_status_btn = Gtk.Button(label="Ricontrolla target")
        self.dg_status_btn.connect(
            "clicked", lambda *_: self.background(self.check_dgvoodoo_target, report=True)
        )
        status_row.append(self.dg_status_btn)
        self.dg_release_btn = Gtk.Button(label="Controlla release ufficiale")
        self.dg_release_btn.connect(
            "clicked", lambda *_: self.background(self.check_dgvoodoo_release)
        )
        status_row.append(self.dg_release_btn)

        actions_frame = Gtk.Frame(label="Azioni")
        page.append(actions_frame)
        actions_box = self.frame_box(actions_frame)
        note = Gtk.Label(
            label=(
                "Payload e attivazione Wine sono separati. “Installa payload” copia soltanto i wrapper selezionati "
                "accanto all'executable e crea backup/manifest. “Attiva per-app” aggiunge AppDefaults per il "
                "basename di quell'executable: Wine usa il basename e RetroCD rifiuta due target gestiti con lo "
                "stesso nome nella stessa bottle. Disattivazione e disinstallazione ripristinano gli snapshot precedenti."
            ),
            xalign=0,
            wrap=True,
        )
        note.add_css_class("dim-label")
        actions_box.append(note)

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions_box.append(action_row)
        self.dg_install_btn = Gtk.Button(label="Installa payload")
        self.dg_install_btn.add_css_class("suggested-action")
        self.dg_install_btn.connect("clicked", lambda *_: self.background(self.install_dgvoodoo_payload))
        action_row.append(self.dg_install_btn)
        self.dg_activate_btn = Gtk.Button(label="Attiva per-app")
        self.dg_activate_btn.connect("clicked", lambda *_: self.background(self.activate_dgvoodoo_target))
        action_row.append(self.dg_activate_btn)
        self.dg_deactivate_btn = Gtk.Button(label="Disattiva per-app")
        self.dg_deactivate_btn.connect("clicked", lambda *_: self.background(self.deactivate_dgvoodoo_target))
        action_row.append(self.dg_deactivate_btn)
        self.dg_uninstall_btn = Gtk.Button(label="Disinstalla / ripristina")
        self.dg_uninstall_btn.connect("clicked", lambda *_: self.background(self.uninstall_dgvoodoo_payload))
        action_row.append(self.dg_uninstall_btn)

        tool_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        actions_box.append(tool_row)
        self.dg_cpl_btn = Gtk.Button(label="Apri dgVoodooCpl")
        self.dg_cpl_btn.connect("clicked", lambda *_: self.background(self.launch_dgvoodoo_control_panel))
        tool_row.append(self.dg_cpl_btn)
        self.dg_copy_override_btn = Gtk.Button(label="Copia override preview")
        self.dg_copy_override_btn.connect("clicked", self.copy_dgvoodoo_override_preview)
        tool_row.append(self.dg_copy_override_btn)

        boundary = Gtk.Label(
            label=(
                "Confine invariato: questa scheda non modifica services.toml, rete, GPU, CDEmu/VHBA o mount. "
                "Il download avviene host-side; il processo Windows continua a usare la stessa istanza Bubblejail "
                "con rete OFF salvo scelta esplicita già prevista dal launcher RetroCD."
            ),
            xalign=0,
            wrap=True,
        )
        boundary.add_css_class("dim-label")
        page.append(boundary)

    def selected_dg_bottle(self) -> BottleInfo:
        if not self._dg_bottles:
            raise DgVoodooError("Nessuna bottle Bottles rilevata.")
        index = self.ui_get(self.dg_bottle_drop.get_selected)
        if index == Gtk.INVALID_LIST_POSITION or index >= len(self._dg_bottles):
            raise DgVoodooError("Seleziona una bottle valida.")
        return self._dg_bottles[index]

    def selected_dg_target(self) -> tuple[BottleInfo, Path]:
        bottle = self.selected_dg_bottle()
        target = self._dg_target
        if target is None:
            raise DgVoodooError("Seleziona prima l'executable Windows da gestire.")
        exe, _arch = validate_game_target(target, bottle)
        return bottle, exe

    def selected_dg_wrappers(self) -> tuple[Wrapper, ...]:
        values = self.ui_get(
            lambda: tuple(
                wrapper
                for wrapper, switch in self.dg_wrapper_switches.items()
                if switch.get_active()
            )
        )
        if not values:
            raise DgVoodooError("Seleziona almeno un wrapper dgVoodoo2.")
        if Wrapper.GLIDE3X in values and Wrapper.GLIDE3X_NAPALM in values:
            raise DgVoodooError("Glide3 standard e Glide3 Napalm sono mutuamente esclusivi.")
        return values

    def refresh_dgvoodoo_bottles(self):
        previous = ""
        if self._dg_bottles and hasattr(self, "dg_bottle_drop"):
            old = self.dg_bottle_drop.get_selected()
            if old != Gtk.INVALID_LIST_POSITION and old < len(self._dg_bottles):
                previous = self._dg_bottles[old].name
        try:
            storage, bottles = discover_bottles(self.sandbox.private_home)
            self._dg_storage = storage
            self._dg_bottles = bottles
            self.dg_bottle_model.splice(0, self.dg_bottle_model.get_n_items(), [b.name for b in bottles])
            if bottles:
                index = next((i for i, b in enumerate(bottles) if b.name == previous), 0)
                self.dg_bottle_drop.set_selected(index)
                self.dg_bottle_drop.set_sensitive(not self.busy)
                self.dg_exe_btn.set_sensitive(not self.busy)
            else:
                self.dg_bottle_drop.set_sensitive(False)
                self.dg_exe_btn.set_sensitive(False)
            source = f"{storage.source} · {storage.root}"
            if self._dg_target is None:
                self.dg_target_status.set_text(f"Storage Bottles: {source} · target non selezionato")
        except Exception as exc:
            self._dg_storage = None
            self._dg_bottles = ()
            self.dg_bottle_model.splice(0, self.dg_bottle_model.get_n_items(), [])
            self.dg_target_status.set_text(f"Discovery Bottles FAIL: {exc}")
            self.dg_bottle_drop.set_sensitive(False)
            self.dg_exe_btn.set_sensitive(False)
        self._update_dg_action_sensitivity()
        return False

    def _dg_bottle_changed(self, *_):
        if not hasattr(self, "dg_exe_entry"):
            return
        self._dg_target = None
        self.dg_exe_entry.set_text("")
        try:
            bottle = self.selected_dg_bottle()
            self.dg_target_status.set_text(
                f"Bottle: {bottle.name} · drive_c={bottle.drive_c} · seleziona un executable"
            )
        except Exception as exc:
            self.dg_target_status.set_text(f"Target: {exc}")
        self._set_dg_wrapper_selection(())
        self.refresh_dgvoodoo_local_status()

    def choose_dgvoodoo_executable(self):
        try:
            bottle = self.selected_dg_bottle()
        except Exception as exc:
            self.set_message(str(exc), True)
            return

        dialog = Gtk.FileChooserNative.new(
            "Scegli executable Windows per dgVoodoo2",
            self,
            Gtk.FileChooserAction.OPEN,
            "_Scegli",
            "_Annulla",
        )
        dialog.set_current_folder(Gio.File.new_for_path(str(bottle.drive_c)))
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Executable Windows (*.exe)")
        file_filter.add_pattern("*.exe")
        file_filter.add_pattern("*.EXE")
        dialog.set_filter(file_filter)

        def response(dlg, response_id):
            try:
                if response_id != Gtk.ResponseType.ACCEPT:
                    return
                chosen = dlg.get_file()
                raw = chosen.get_path() if chosen else None
                if not raw:
                    raise DgVoodooError("Nessun executable selezionato.")
                exe, arch = validate_game_target(Path(raw), bottle)
                self._dg_target = exe
                try:
                    relative = exe.relative_to(bottle.drive_c)
                except ValueError:
                    relative = exe
                self.dg_exe_entry.set_text(str(relative))
                self.dg_target_status.set_text(
                    f"Target valido: {exe} · PE {arch.value} · bottle {bottle.name}"
                )
                self.refresh_dgvoodoo_local_status()
            except Exception as exc:
                self._dg_target = None
                self.dg_exe_entry.set_text("")
                self.set_message(str(exc), True)
                self.refresh_dgvoodoo_local_status()
            finally:
                dlg.destroy()

        dialog.connect("response", response)
        dialog.show()

    def _dg_wrapper_changed(self, switch, _param, wrapper: Wrapper):
        if self._dg_syncing_wrappers:
            return
        if switch.get_active():
            self._dg_syncing_wrappers = True
            try:
                if wrapper == Wrapper.GLIDE3X:
                    self.dg_wrapper_switches[Wrapper.GLIDE3X_NAPALM].set_active(False)
                elif wrapper == Wrapper.GLIDE3X_NAPALM:
                    self.dg_wrapper_switches[Wrapper.GLIDE3X].set_active(False)
            finally:
                self._dg_syncing_wrappers = False
        self._render_dg_override_preview()

    def _set_dg_wrapper_selection(self, wrappers: tuple[Wrapper, ...]):
        if not hasattr(self, "dg_wrapper_switches"):
            return
        selected = set(wrappers)
        self._dg_syncing_wrappers = True
        try:
            for wrapper, switch in self.dg_wrapper_switches.items():
                switch.set_active(wrapper in selected)
        finally:
            self._dg_syncing_wrappers = False
        self._render_dg_override_preview()

    def _render_dg_override_preview(self):
        if not hasattr(self, "dg_override_preview"):
            return False
        wrappers = tuple(
            wrapper
            for wrapper, switch in self.dg_wrapper_switches.items()
            if switch.get_active()
        )
        if not wrappers:
            self.dg_override_preview.set_text("Wine AppDefaults preview: seleziona almeno un wrapper")
            self.dg_copy_override_btn.set_sensitive(False)
        elif Wrapper.GLIDE3X in wrappers and Wrapper.GLIDE3X_NAPALM in wrappers:
            self.dg_override_preview.set_text("Wine AppDefaults preview: selezione Glide3 ambigua")
            self.dg_copy_override_btn.set_sensitive(False)
        else:
            self.dg_override_preview.set_text(
                "Wine AppDefaults preview: " + wine_overrides_value(wrappers)
            )
            self.dg_copy_override_btn.set_sensitive(not self.busy)
        return False

    def _local_dg_state(self) -> tuple[InstallationState | None, object | None]:
        if self._dg_target is None or not self._dg_bottles:
            return None, None
        bottle, exe = self.selected_dg_target()
        payload = inspect_installation(bottle, exe)
        activation = activation_status(bottle, exe)
        return payload, activation

    def refresh_dgvoodoo_local_status(self):
        if not hasattr(self, "dg_install_status"):
            return False
        try:
            payload, activation = self._local_dg_state()
            if payload is None or activation is None:
                self.dg_install_status.set_text("Payload: seleziona un executable")
                self.dg_activation_status.set_text("Wine AppDefaults: seleziona un executable")
                self._update_dg_action_sensitivity(None, None)
                return False

            if payload.state == "inactive":
                self.dg_install_status.set_text(f"Payload: non installato · PE {payload.arch}")
            elif payload.state == "installed":
                wrappers = ", ".join(item.value for item in payload.wrappers)
                preserved = ", ".join(path.name for path in payload.preserved_files) or "nessuno"
                self.dg_install_status.set_text(
                    f"Payload: PASS · dgVoodoo2 {payload.version} · {payload.arch} · wrapper [{wrappers}] · "
                    f"preservati [{preserved}]"
                )
                self._set_dg_wrapper_selection(payload.wrappers)
            else:
                self.dg_install_status.set_text(
                    "Payload: CONFLITTO · " + " · ".join(payload.problems)
                )
                self._set_dg_wrapper_selection(payload.wrappers)

            if activation.state == "inactive":
                self.dg_activation_status.set_text("Wine AppDefaults: inattivo")
            else:
                names = ", ".join(activation.overrides)
                self.dg_activation_status.set_text(
                    f"Wine AppDefaults: {activation.state.upper()} · [{names}] · snapshot RetroCD presente"
                )
            self._update_dg_action_sensitivity(payload, activation)
        except Exception as exc:
            self.dg_install_status.set_text(f"Payload/stato: FAIL · {exc}")
            self.dg_activation_status.set_text("Wine AppDefaults: non determinabile")
            self._update_dg_action_sensitivity(None, None)
        return False

    def check_dgvoodoo_release(self):
        release = fetch_latest_release()
        cache = manager_cache_dir() / "releases" / release.tag / release.asset_name
        cached = False
        if cache.is_file() and not cache.is_symlink():
            try:
                cached = cache.stat().st_size == release.size and sha256_file(cache) == release.sha256
            except OSError:
                cached = False
        self._dg_latest_release = release
        GLib.idle_add(self._render_dg_release_status, release, cache, cached)
        return (
            f"Release ufficiale dgVoodoo2 verificata: {release.tag} · "
            f"cache {'verificata' if cached else 'non presente/non valida'}"
        )

    def _render_dg_release_status(self, release: ReleaseInfo, cache: Path, cached: bool):
        self.dg_release_status.set_text(
            f"Release ufficiale: {release.tag} · asset {release.asset_name} · SHA-256 {release.sha256} · "
            f"cache {'PASS' if cached else 'assente'} ({cache})"
        )
        return False

    def check_dgvoodoo_target(self):
        bottle, exe = self.selected_dg_target()
        payload = inspect_installation(bottle, exe)
        activation = activation_status(bottle, exe)
        lines = [
            f"[INFO] Bottle: {bottle.name}",
            f"[INFO] Executable: {exe}",
            f"[INFO] Payload: {payload.state}",
            f"[INFO] AppDefaults transaction: {activation.state}",
        ]
        if payload.problems:
            for item in payload.problems:
                lines.append(f"[FAIL] {item}")
            raise DgVoodooError("Integrità payload dgVoodoo2 non valida.\n" + "\n".join(lines))
        if activation.state == "active":
            for name in activation.overrides:
                observed = query_app_override(bottle, exe, name)
                if observed != "n,b":
                    raise DgVoodooError(
                        f"Override {name} non corrisponde allo stato gestito: {observed!r}."
                    )
                lines.append(f"[PASS] AppDefaults {name}=n,b")
        elif activation.state == "pending":
            raise DgVoodooError("Transazione AppDefaults rimasta pending; intervento conservativo richiesto.")
        else:
            lines.append("[PASS] Nessuna transazione AppDefaults RetroCD attiva")
        GLib.idle_add(self.refresh_dgvoodoo_local_status)
        return "\n".join(lines)

    def _dg_mutation_preflight(self):
        if self.sandbox.running():
            raise DgVoodooError(
                "Chiudi Bottles/Bubblejail prima di modificare payload o AppDefaults dgVoodoo2."
            )

    def install_dgvoodoo_payload(self):
        self._dg_mutation_preflight()
        bottle, exe = self.selected_dg_target()
        current = inspect_installation(bottle, exe)
        if current.state != "inactive":
            raise DgVoodooError(
                "Esiste già un payload dgVoodoo2 gestito per questo executable; ripristinalo prima."
            )
        wrappers = self.selected_dg_wrappers()
        release = fetch_latest_release()
        archive = download_release(release)
        report = install_wrappers(archive, release, bottle, exe, wrappers)
        self._dg_latest_release = release
        GLib.idle_add(self.refresh_dgvoodoo_local_status)
        return (
            f"[PASS] Payload dgVoodoo2 {report.version} installato per {exe.name} · {report.arch.value} · "
            f"wrapper={','.join(item.value for item in report.wrappers)} · AppDefaults ancora inattivo"
        )

    def activate_dgvoodoo_target(self):
        self._dg_mutation_preflight()
        bottle, exe = self.selected_dg_target()
        payload = inspect_installation(bottle, exe)
        if payload.state == "inactive":
            raise DgVoodooError("Installa prima il payload dgVoodoo2.")
        if payload.state != "installed":
            raise DgVoodooError("Payload dgVoodoo2 modificato/conflittuale: attivazione rifiutata.")
        current = activation_status(bottle, exe)
        if current.state != "inactive":
            raise DgVoodooError(f"AppDefaults dgVoodoo2 già in stato {current.state}.")
        names = wine_override_names(payload.wrappers)
        result = activate_app_overrides(bottle, exe, names)
        GLib.idle_add(self.refresh_dgvoodoo_local_status)
        return (
            f"[PASS] dgVoodoo2 attivato solo per {result.app_name}: "
            + ";".join(f"{name}=n,b" for name in result.overrides)
        )

    def deactivate_dgvoodoo_target(self):
        self._dg_mutation_preflight()
        bottle, exe = self.selected_dg_target()
        current = activation_status(bottle, exe)
        if current.state == "inactive":
            return "dgVoodoo2 AppDefaults già inattivo per questo executable."
        result = deactivate_app_overrides(bottle, exe)
        GLib.idle_add(self.refresh_dgvoodoo_local_status)
        return f"[PASS] AppDefaults dgVoodoo2 ripristinato per {result.app_name}."

    def uninstall_dgvoodoo_payload(self):
        self._dg_mutation_preflight()
        bottle, exe = self.selected_dg_target()
        payload = inspect_installation(bottle, exe)
        if payload.state == "inactive":
            raise DgVoodooError("Nessun payload dgVoodoo2 gestito da ripristinare.")
        current = activation_status(bottle, exe)
        if current.state != "inactive":
            deactivate_app_overrides(bottle, exe)
        restored = uninstall_wrappers(bottle, exe)
        GLib.idle_add(self.refresh_dgvoodoo_local_status)
        return (
            f"[PASS] dgVoodoo2 disinstallato/ripristinato per {exe.name} · "
            f"file gestiti ripristinati/rimossi={len(restored)}"
        )

    def launch_dgvoodoo_control_panel(self):
        self._dg_mutation_preflight()
        bottle, exe = self.selected_dg_target()
        payload = inspect_installation(bottle, exe)
        if payload.state != "installed":
            raise DgVoodooError("Control panel disponibile solo con payload integro installato.")
        cpl = payload.control_panel
        if cpl is None or cpl.is_symlink() or not cpl.is_file():
            raise DgVoodooError("dgVoodooCpl.exe gestito non disponibile per questo target.")
        command = [
            "bubblejail", "run", "--wait", INSTANCE,
            "bottles-cli", "run", "-b", bottle.name, "-e", str(cpl),
        ]
        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if result.returncode != 0:
            tail = "\n".join((result.stdout or "").splitlines()[-20:])
            raise DgVoodooError(f"dgVoodooCpl terminato con rc={result.returncode}:\n{tail}")
        return f"dgVoodooCpl chiuso per {exe.name}; configurazione per-game lasciata nella directory target."

    def copy_dgvoodoo_override_preview(self, *_):
        try:
            wrappers = tuple(
                wrapper
                for wrapper, switch in self.dg_wrapper_switches.items()
                if switch.get_active()
            )
            if not wrappers:
                raise DgVoodooError("Nessun override da copiare.")
            value = wine_overrides_value(wrappers)
            self.get_clipboard().set(value)
            self.set_message("Override dgVoodoo2 copiato: " + value)
        except Exception as exc:
            self.set_message(str(exc), True)

    def _update_dg_action_sensitivity(self, payload=None, activation=None):
        if not hasattr(self, "dg_install_btn"):
            return False
        has_target = self._dg_target is not None and bool(self._dg_bottles)
        if has_target and payload is None and activation is None:
            try:
                payload, activation = self._local_dg_state()
            except Exception:
                payload = activation = None
        inactive_payload = payload is not None and payload.state == "inactive"
        intact_payload = payload is not None and payload.state == "installed"
        has_payload = payload is not None and payload.active_payload
        inactive_activation = activation is not None and activation.state == "inactive"
        active_activation = activation is not None and activation.state in {"active", "pending"}
        enabled = not self.busy and has_target
        self.dg_install_btn.set_sensitive(enabled and inactive_payload)
        self.dg_activate_btn.set_sensitive(enabled and intact_payload and inactive_activation)
        self.dg_deactivate_btn.set_sensitive(enabled and active_activation)
        self.dg_uninstall_btn.set_sensitive(enabled and has_payload)
        self.dg_cpl_btn.set_sensitive(enabled and intact_payload and payload.control_panel is not None)
        self.dg_status_btn.set_sensitive(enabled)
        self.dg_release_btn.set_sensitive(not self.busy)
        self.dg_bottle_refresh_btn.set_sensitive(not self.busy)
        self.dg_bottle_drop.set_sensitive(not self.busy and bool(self._dg_bottles))
        self.dg_exe_btn.set_sensitive(not self.busy and bool(self._dg_bottles))
        for switch in self.dg_wrapper_switches.values():
            switch.set_sensitive(enabled and inactive_payload)
        self._render_dg_override_preview()
        return False

    def refresh_all(self):
        result = super().refresh_all()
        if hasattr(self, "dg_install_status"):
            self.refresh_dgvoodoo_local_status()
        return result

    def set_busy(self, busy: bool):
        super().set_busy(busy)
        if hasattr(self, "dg_install_btn"):
            self._update_dg_action_sensitivity()


_life._ext._base.Window = Window
App = _life.App

if __name__ == "__main__":
    raise SystemExit(App().run())
