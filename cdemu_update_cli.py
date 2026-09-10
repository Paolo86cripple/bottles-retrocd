#!/usr/bin/env python3
from __future__ import annotations

import shutil
import subprocess

from cdemu_lifecycle import format_report, inspect_lifecycle, update_command
from cdemu_ownership import CDEmuOwnershipBusy, CDEmuOwnershipError, CDEmuOwnershipStore
from sandbox_backend import INSTANCE, SandboxBackend

SERVICE = "cdemu-daemon.service"


def _restart_user_daemon(should_start: bool) -> None:
    if not should_start:
        return
    result = subprocess.run(
        ["systemctl", "--user", "start", SERVICE],
        check=False,
    )
    if result.returncode != 0:
        print(f"[WARN] Impossibile riavviare {SERVICE}; esegui manualmente: systemctl --user start {SERVICE}")


def _media_preflight() -> tuple[bool, str]:
    # Keep the updater module importable in headless/static CI. PyGObject is only
    # needed when this real host-side D-Bus preflight is actually executed.
    try:
        from cdemu_backend import CDEmuBackend
    except Exception as exc:
        return False, f"Backend CDEmu non disponibile: {exc}"

    try:
        backend = CDEmuBackend()
    except Exception as exc:
        return False, f"CDEmu non raggiungibile: {exc}"
    try:
        loaded = [device.index for device in backend.devices() if device.loaded]
    except Exception as exc:
        return False, f"Impossibile leggere lo stato dei device CDEmu: {exc}"
    finally:
        backend.close()
    if loaded:
        return False, (
            "Media ancora caricati nei device CDEmu: "
            + ", ".join(f"#{index}" for index in loaded)
            + ". Usa 'Espelli tutto' prima di aggiornare."
        )
    return True, ""


def _run_locked_update() -> int:
    """Run all preflights and the package transaction while ownership is locked."""
    if SandboxBackend(INSTANCE).running():
        print("[FAIL] Bottles/Bubblejail è attivo. Chiudilo completamente prima di aggiornare.")
        return 2

    media_ok, media_error = _media_preflight()
    if not media_ok:
        print(f"[FAIL] {media_error}")
        return 2

    report = inspect_lifecycle()
    print(format_report(report))
    if not report.ok:
        print("\n[FAIL] Health check non valido: aggiornamento rifiutato.")
        return 2

    if shutil.which("sudo") is None:
        print("\n[FAIL] sudo non disponibile; impossibile eseguire l'aggiornamento interattivo.")
        return 2

    command = update_command(report)
    print("\nTransazione proposta:")
    print("  " + " ".join(command))
    print(
        "\nNota: è un aggiornamento Arch/CachyOS completo (-Syu), non una partial upgrade. "
        "Pacman mostrerà la transazione e potrai ancora annullare al suo prompt."
    )
    answer = input("\nDigita AGGIORNA per continuare: ").strip()
    if answer != "AGGIORNA":
        print("Operazione annullata. Nessun pacchetto modificato.")
        return 0

    # Re-check immediately before touching the daemon. The ownership flock has
    # prevented any cooperating RetroCD process from changing CDEmu since the
    # first preflight; this second probe catches uncooperative external clients.
    if SandboxBackend(INSTANCE).running():
        print("[FAIL] Bottles/Bubblejail è diventato attivo; aggiornamento annullato.")
        return 2
    media_ok, media_error = _media_preflight()
    if not media_ok:
        print(f"[FAIL] Stato CDEmu cambiato prima della transazione: {media_error}")
        return 2

    was_active = report.daemon_service_active or report.daemon_reachable
    if was_active:
        stopped = subprocess.run(
            ["systemctl", "--user", "stop", SERVICE],
            check=False,
        )
        if stopped.returncode != 0:
            print(f"[FAIL] Impossibile fermare {SERVICE}; transazione non avviata.")
            return 2

    try:
        result = subprocess.run(list(command), check=False)
    finally:
        _restart_user_daemon(was_active)

    if result.returncode != 0:
        print(f"\n[FAIL] pacman è terminato con codice {result.returncode}.")
        return result.returncode or 1

    print("\nTransazione pacman completata. Nuovo health check:\n")
    after = inspect_lifecycle()
    print(format_report(after))
    if after.ok:
        print("\n[PASS] Componenti Retro Optical aggiornati e health check valido.")
        return 0

    if report.vhba_provider.startswith("kernel:") and any(
        "modinfo non trova" in failure or "fuori dalla directory del kernel corrente" in failure
        for failure in after.failures
    ):
        print(
            "\n[WARN] La transazione è riuscita ma il pacchetto kernel può essere cambiato mentre "
            "stai ancora eseguendo il kernel precedente. Riavvia il sistema e ripeti il health check."
        )
        return 3

    print("\n[WARN] La transazione è riuscita ma il health check post-update non è completamente valido.")
    return 3


def main() -> int:
    print("Bottles RetroCD · aggiornamento componenti Retro Optical")
    print("=========================================================\n")

    store = CDEmuOwnershipStore()
    try:
        with store.operation(timeout=0.5):
            if store.load() is not None:
                print(
                    "[FAIL] Esiste un journal ownership CDEmu non risolto. "
                    "Apri Bottles RetroCD e completa prima il recovery/cleanup."
                )
                return 2
            return _run_locked_update()
    except CDEmuOwnershipBusy as exc:
        print(f"[FAIL] {exc}")
        return 2
    except CDEmuOwnershipError as exc:
        print(f"[FAIL] Impossibile provare il lock/ownership CDEmu: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
