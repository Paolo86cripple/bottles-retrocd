#!/usr/bin/env python3
"""0.4.1 hardening wrapper for verifier/updater and CDEmu ownership."""
from __future__ import annotations

import importlib.util
from contextlib import contextmanager
from pathlib import Path

GAMEPAD_GUI = Path(__file__).with_name("bottles-retro-cd-gui-gamepad.py")
_spec = importlib.util.spec_from_file_location("_bottles_retro_cd_gamepad", GAMEPAD_GUI)
if _spec is None or _spec.loader is None:
    raise RuntimeError(f"Impossibile caricare la GUI RetroCD gamepad: {GAMEPAD_GUI}")
_game = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_game)

Gtk = _game.Gtk
GLib = _game.GLib

from cdemu_ownership import (  # noqa: E402
    CDEmuOwnershipBusy,
    CDEmuOwnershipError,
    CDEmuOwnershipStore,
    OwnedDevice,
    block_rdev,
    cleanup_owned_session,
)
from verifier_sandbox import VerifierSandbox  # noqa: E402
from verifier_updater_sandbox import VerifierUpdaterSandbox  # noqa: E402


class Window(_game.Window):
    """Preserve the released game boundary while hardening host-side helpers."""

    def __init__(self, app):
        # Base construction schedules initialize() via GLib.idle_add. Create the
        # ownership store first so the virtual initialize override always sees it.
        self.cdemu_ownership = CDEmuOwnershipStore()
        super().__init__(app)
        self.verifier_sandbox = VerifierSandbox()
        self.updater_sandbox = VerifierUpdaterSandbox()
        self._install_verifier_sandbox_test()

    # ------------------------------------------------------------------
    # Verifier / updater boundaries already target-validated in 0.4.1.
    # ------------------------------------------------------------------
    def _verifier_root(self) -> Path:
        root = getattr(self, "_archive_root", None)
        if not isinstance(root, Path) or not root.is_dir():
            raise RuntimeError("Configura prima una radice archivio RetroCD valida.")
        return root

    def _install_verifier_sandbox_test(self) -> None:
        self.verifier_sandbox_test_btn = Gtk.Button(label="Test verifica sandbox")
        self.verifier_sandbox_test_btn.set_tooltip_text(
            "Prova l'isolamento bwrap della verifica senza modificare i dump: archivio/codice/catalogo RO, "
            "sola cache di verifica RW, HOME host nascosta e rete host non condivisa."
        )
        self.verifier_sandbox_test_btn.connect(
            "clicked", lambda *_: self.background(self.test_verifier_sandbox, report=True)
        )
        parent = self.update_redump_btn.get_parent()
        if isinstance(parent, Gtk.Box):
            parent.append(self.verifier_sandbox_test_btn)
        else:
            raise RuntimeError("Layout Verifica inatteso: impossibile inserire Test verifica sandbox.")

    def test_verifier_sandbox(self) -> str:
        result = self.verifier_sandbox.attest(self._verifier_root())
        text = result.format()
        GLib.idle_add(self.verifier_result.set_text, text)
        return text

    def _update_catalog(self, source: str):
        report = self.updater_sandbox.update(source, archive_root=self._verifier_root())
        GLib.idle_add(self.refresh_verifier_status)
        return self._format_update(report)

    def verify_selected_image(self):
        descriptor = self.selected_image()
        result = self.verifier_sandbox.verify(descriptor, self._verifier_root())
        GLib.idle_add(self.verifier_result.set_text, result.text)
        return result.text

    def verify_selected_set(self):
        descriptors = self.ui_get(
            lambda: tuple(entry.image for entry in self.disc_set.discs)
            if self.disc_set is not None and self.disc_set.discs else ()
        )
        if len(descriptors) < 2:
            raise RuntimeError("Il disco selezionato non appartiene a un set multidisco con almeno due supporti.")
        result = self.verifier_sandbox.verify_set(descriptors, self._verifier_root())
        GLib.idle_add(self.verifier_result.set_text, result.text)
        return result.text

    def scan_selected_image(self):
        descriptor = self.selected_image()
        result = self.verifier_sandbox.scan(descriptor, self._verifier_root())
        GLib.idle_add(self.verifier_result.set_text, result.text)
        return result.text

    def verify_and_scan_selected(self):
        descriptor = self.selected_image()
        result = self.verifier_sandbox.verify_scan(descriptor, self._verifier_root())
        GLib.idle_add(self.verifier_result.set_text, result.text)
        return result.text

    # ------------------------------------------------------------------
    # CDEmu inter-process ownership and crash recovery.
    # ------------------------------------------------------------------
    def _cleanup_owned_journal(self, *, stale_recovery: bool) -> tuple[str, ...]:
        if self.cdemu is None:
            raise CDEmuOwnershipError("CDEmu non connesso: ownership non verificabile.")
        result = cleanup_owned_session(
            self.cdemu_ownership,
            self.cdemu,
            mount_info=self.mount_info,
            unmount=self.unmount,
            validate_optical=self.validate_cdemu_optical_device,
            stale_recovery=stale_recovery,
            sandbox_running=self.sandbox.running(),
        )
        return result.messages

    def _recover_stale_cdemu_state(self) -> str:
        """Recover a previous crashed session only after acquiring its released lock."""
        if self.cdemu is None or self.cdemu_ownership.session_locked:
            return ""
        self.cdemu_ownership.acquire_session_lock(timeout=0.25)
        try:
            session = self.cdemu_ownership.load()
            if session is None:
                return ""
            if self.sandbox.running():
                return (
                    "Recovery CDEmu rinviato: esiste un journal precedente ma Bottles/Bubblejail è ancora attivo; "
                    "nessun device viene toccato."
                )
            messages = self._cleanup_owned_journal(stale_recovery=True)
            return "Recovery CDEmu: " + "; ".join(messages)
        finally:
            self.cdemu_ownership.release_session_lock()

    @contextmanager
    def _cdemu_operation(self):
        """Serialize mutating CDEmu work and resolve stale ownership first."""
        if not self.cdemu_ownership.session_locked:
            self._recover_stale_cdemu_state()
        with self.cdemu_ownership.operation(timeout=2.0):
            session = self.cdemu_ownership.load()
            if session is not None and not self.cdemu_ownership.session_locked:
                raise CDEmuOwnershipError(
                    "Journal CDEmu non risolto: operazione mutante rifiutata finché ownership/recovery non è provato."
                )
            yield

    def initialize(self):
        result = super().initialize()
        if self.cdemu is not None:
            try:
                recovery = self._recover_stale_cdemu_state()
            except CDEmuOwnershipBusy as exc:
                self.set_message(
                    f"CDEmu ownership: {exc} Le letture restano disponibili; le mutazioni saranno rifiutate.",
                    True,
                )
            except Exception as exc:
                self.set_message(f"Recovery CDEmu sospeso in sicurezza: {exc}", True)
            else:
                if recovery:
                    self.set_message(recovery)
        return result

    def _prepare_disc_cache(self, disc_set):
        """Create a live multidisc cache with write-ahead ownership evidence."""
        if self.cdemu is None:
            raise RuntimeError("CDEmu non connesso.")
        if not disc_set.multidisc:
            raise RuntimeError("La cache live richiede un set multidisco.")

        self.cdemu_ownership.acquire_session_lock(timeout=2.0)
        journal_started = False
        cache: dict[str, tuple[int, str, str]] = {}
        base_count: int | None = None
        try:
            if self.cdemu_ownership.load() is not None:
                raise CDEmuOwnershipError("Esiste un journal CDEmu non risolto: nuova cache live rifiutata.")
            base_count = self.cdemu.number_of_devices()
            expected_images = tuple(str(entry.image.resolve(strict=True)) for entry in disc_set.discs)
            self.cdemu_ownership.begin(
                daemon_identity=self.cdemu.daemon_identity(),
                base_count=base_count,
                expected_images=expected_images,
            )
            journal_started = True

            for entry in disc_set.discs:
                image = entry.image.resolve(strict=True)
                session = self.cdemu_ownership.load()
                if session is None:
                    raise CDEmuOwnershipError("Journal CDEmu scomparso durante preparazione.")
                expected_index = session.base_count + len(session.resources)
                self.cdemu_ownership.set_pending(index=expected_index, image=str(image))
                index = self.cdemu.add_device()
                if index != expected_index:
                    raise CDEmuOwnershipError(f"AddDevice ha restituito #{index}, atteso esattamente #{expected_index}.")
                sr, sg = self.cdemu.wait_mapping(index)
                self.validate_cdemu_optical_device(sr)
                self.cdemu.load(index, image)
                loaded, filenames = self.cdemu.wait_loaded(index, True)
                actual = tuple(str(Path(name).resolve(strict=False)) for name in filenames)
                if not loaded or actual != (str(image),):
                    raise CDEmuOwnershipError(
                        f"Device #{index}: media caricato non coincide con l'immagine attesa: {actual!r}."
                    )
                self.apply_options(index)
                mount = self.ensure_ro_mount(sr)
                target, ro = self.mount_info(sr)
                if not target or not ro or target != mount:
                    raise CDEmuOwnershipError(f"Cache Disco {entry.number}: mount RO non verificato per {sr}.")
                resource = OwnedDevice(index, str(image), sr, sg, mount, block_rdev(sr))
                self.cdemu_ownership.commit_pending(resource)
                cache[self._disc_cache_key(image)] = (index, sr, mount)

            self.cdemu_ownership.activate()
            if len(cache) != len(disc_set.discs):
                raise CDEmuOwnershipError("Cache multidisco incompleta dopo attivazione journal.")
            return cache, base_count
        except Exception as primary:
            warnings: list[str] = []
            if journal_started:
                warnings = self._cleanup_disc_cache(cache, base_count)
            else:
                self.cdemu_ownership.release_session_lock()
            suffix = f" Cleanup ownership: {'; '.join(warnings)}" if warnings else ""
            raise RuntimeError(f"Preparazione cache CDEmu fallita: {primary}.{suffix}") from primary

    def _cleanup_disc_cache(self, cache, base_count):
        """Replace RAM-only suffix cleanup with journal-authorized cleanup."""
        if not self.cdemu_ownership.session_locked:
            try:
                self.cdemu_ownership.acquire_session_lock(timeout=0.25)
            except Exception as exc:
                return [f"lock CDEmu non acquisibile per cleanup: {exc}"]
        try:
            session = self.cdemu_ownership.load()
            if session is None:
                if cache:
                    return ["cache CDEmu presente senza journal ownership: RemoveDevice rifiutato"]
                return []
            if base_count is not None and base_count != session.base_count:
                return [f"base_count cache={base_count} diverso dal journal={session.base_count}: cleanup rifiutato"]
            self._cleanup_owned_journal(stale_recovery=False)
            return []
        except Exception as exc:
            return [f"cleanup ownership sospeso: {exc}"]
        finally:
            self.cdemu_ownership.release_session_lock()

    def _cleanup_inactive_live_session(self):
        if self.sandbox.running():
            return ["cleanup non eseguito: Bottles/Bubblejail è nuovamente attivo"] if self.active_bridge_cache else []
        if not self.active_bridge_cache:
            recovery = self._recover_stale_cdemu_state()
            return [recovery] if recovery else []

        if self.active_bridge is not None:
            self.active_bridge.stop()
        warnings = self._cleanup_disc_cache(dict(self.active_bridge_cache), self.active_bridge_cache_base_count)
        if warnings:
            return warnings
        self.active_bridge = None
        self.active_bridge_device_index = None
        self.active_bridge_sr = ""
        self.active_bridge_cache = {}
        self.active_bridge_cache_base_count = None
        return []

    # Short non-live mutations use the same flock. The live path upgrades to a
    # persistent lease before creating its first appended cache device.
    def swap_to_image(self, image: Path):
        with self._cdemu_operation():
            return super().swap_to_image(image)

    def eject_selected_device(self):
        with self._cdemu_operation():
            return super().eject_selected_device()

    def apply_options_selected(self):
        with self._cdemu_operation():
            return super().apply_options_selected()

    def run_cdemu_test(self):
        with self._cdemu_operation():
            return super().run_cdemu_test()

    def run_integration_test(self):
        with self._cdemu_operation():
            return super().run_integration_test()

    def eject_all_retrocd_media(self):
        # Parent eject-all cleans a live cache first, which intentionally ends
        # the persistent lease. Split the operation so the remaining unloads
        # are then covered by a fresh short lock rather than running unlocked.
        if self.sandbox.running():
            return super().eject_all_retrocd_media()
        had_cache = bool(self.active_bridge_cache)
        if had_cache:
            notes = self._cleanup_inactive_live_session()
            if notes:
                raise CDEmuOwnershipError("Espelli tutto: cleanup cache ownership non completato: " + "; ".join(notes))
        with self._cdemu_operation():
            text = super().eject_all_retrocd_media()
        if had_cache:
            return text.rstrip(".") + " · cache multidisco ownership ripulita."
        return text

    def launch_bottles(self):
        live_requested = bool(self.ui_get(self.live_multidisc_switch.get_active))
        if not live_requested:
            with self._cdemu_operation():
                return super().launch_bottles()

        # Hold the same lease through preparation, the entire live game session
        # and final cache cleanup. O_CLOEXEC prevents leaking it into Bottles.
        self.cdemu_ownership.acquire_session_lock(timeout=2.0)
        try:
            if self.cdemu_ownership.load() is not None:
                raise CDEmuOwnershipError("Journal CDEmu non risolto prima dell'avvio live.")
            return super().launch_bottles()
        except Exception:
            if not self.active_bridge_cache:
                self.cdemu_ownership.release_session_lock()
            raise

    def _runtime_update_preflight(self):
        super()._runtime_update_preflight()
        if self.cdemu_ownership.session_locked:
            raise CDEmuOwnershipError("Sessione ownership CDEmu ancora attiva: aggiornamento componenti rifiutato.")
        with self.cdemu_ownership.operation(timeout=0.25):
            if self.cdemu_ownership.load() is not None:
                raise CDEmuOwnershipError("Journal CDEmu non risolto: aggiornamento componenti rifiutato.")

    def on_close_request(self, *args):
        blocked = super().on_close_request(*args)
        if not blocked:
            self.cdemu_ownership.close()
        return blocked

    def set_busy(self, busy: bool):
        super().set_busy(busy)
        button = getattr(self, "verifier_sandbox_test_btn", None)
        if button is not None:
            button.set_sensitive(not busy)


_game._release_base.Window = Window
App = _game.App

if __name__ == "__main__":
    raise SystemExit(App().run())
