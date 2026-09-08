#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from bottles_storage import discover_bottles
from dgvoodoo_backend import (
    BottleInfo,
    DgVoodooError,
    fetch_latest_release,
    validate_game_target,
)
from dgvoodoo_probe import (
    clean_probe,
    install_probe,
    prepare_probe,
    probe_status,
    tamper_refusal_probe,
    uninstall_probe,
)
from dgvoodoo_wine import (
    activate_app_overrides,
    activation_status,
    deactivate_app_overrides,
    query_app_override,
    tamper_refusal_test as override_tamper_refusal_test,
)
from sandbox_backend import INSTANCE, SandboxBackend


def _bottles():
    sandbox = SandboxBackend(INSTANCE)
    storage, bottles = discover_bottles(sandbox.private_home)
    return sandbox, storage, bottles


def _find_bottle(name: str) -> tuple[object, BottleInfo]:
    _sandbox, storage, bottles = _bottles()
    bottle = next((item for item in bottles if item.name == name), None)
    if bottle is None:
        names = ", ".join(item.name for item in bottles) or "nessuna"
        raise DgVoodooError(
            f"Bottle {name!r} non trovata in {storage.root}. Disponibili: {names}"
        )
    return storage, bottle


def _ensure_bottles_closed() -> None:
    sandbox = SandboxBackend(INSTANCE)
    if sandbox.running():
        raise DgVoodooError(
            "Chiudi Bottles/Bubblejail prima di modificare dgVoodoo2 o gli override Wine."
        )


def cmd_inventory(_args) -> int:
    sandbox, storage, bottles = _bottles()
    print(f"Bubblejail instance: {INSTANCE}")
    print(f"Private HOME: {sandbox.private_home}")
    print(f"Bottles storage: {storage.source} · {storage.root}")
    if storage.configured_custom is not None:
        print(f"custom_bottles_path: {storage.configured_custom}")
    print(f"Bottles rilevate: {len(bottles)}")
    for bottle in bottles:
        print(f"  - {bottle.name}: {bottle.root}")
    print()
    release = fetch_latest_release()
    print(f"dgVoodoo2 ufficiale: {release.tag}")
    print(f"Asset: {release.asset_name} · {release.size} byte")
    print(f"SHA-256: {release.sha256}")
    print("Sorgente: dege-diosg/dgVoodoo2")
    print("Nota: metadata soltanto; nessun ZIP è stato scaricato o installato.")
    return 0


def cmd_inspect(args) -> int:
    storage, bottle = _find_bottle(args.bottle)
    raw = Path(args.executable).expanduser()
    executable = raw if raw.is_absolute() else bottle.drive_c / raw
    exe, arch = validate_game_target(executable, bottle)
    print(f"Bottle storage: {storage.source} · {storage.root}")
    print(f"Bottle: {bottle.name}")
    print(f"drive_c: {bottle.drive_c}")
    print(f"Executable: {exe}")
    print(f"PE architecture: {arch.value}")
    print("Target valido per la fase dgVoodoo2 7A; nessun file modificato.")
    return 0


def cmd_probe_prepare(args) -> int:
    _ensure_bottles_closed()
    storage, bottle = _find_bottle(args.bottle)
    status = prepare_probe(bottle)
    print(f"Bottle storage: {storage.source} · {storage.root}")
    print(f"[PASS] Probe x86 preparata: {status.root}")
    print(f"Executable: {status.executable}")
    print("Baseline: DDraw.dll preesistente + dgVoodoo.conf preesistente + unrelated.bin")
    print("Nessun gioco installato; nessun download dgVoodoo2 eseguito.")
    return 0


def cmd_probe_status(args) -> int:
    _storage, bottle = _find_bottle(args.bottle)
    status = probe_status(bottle)
    activation = activation_status(bottle, status.executable)
    print(f"Probe: {status.root}")
    print(f"Executable: {status.executable}")
    print(f"Baseline: {'PASS' if status.baseline_ok else 'MODIFICATA/INSTALLATA'}")
    print(f"DDraw SHA-256: {status.ddraw_sha256}")
    print(f"Config SHA-256: {status.config_sha256}")
    print(f"Unrelated SHA-256: {status.unrelated_sha256}")
    print(f"Wine AppDefaults: {activation.state}")
    return 0


def cmd_probe_install(args) -> int:
    _ensure_bottles_closed()
    _storage, bottle = _find_bottle(args.bottle)
    result = install_probe(bottle)
    print(f"[PASS] dgVoodoo2 {result.release.version} installato nella sola probe.")
    print(f"Archivio verificato: {result.archive}")
    print(f"SHA-256 ufficiale: {result.release.sha256}")
    print(f"Manifest: {result.report.manifest_path}")
    print("Wrapper: DDraw.dll x86")
    print("dgVoodoo.conf preesistente: preservato")
    print("unrelated.bin: invariato")
    print("Wine override PREVIEW soltanto: ddraw=n,b")
    print("Nessun override Wine applicato in questa fase.")
    return 0


def cmd_probe_tamper(args) -> int:
    _ensure_bottles_closed()
    _storage, bottle = _find_bottle(args.bottle)
    message = tamper_refusal_probe(bottle)
    print("[PASS] Modified-file refusal verificato.")
    print(f"Rifiuto osservato: {message}")
    print("La DLL gestita è stata ripristinata ai byte installati; l'installazione probe resta valida.")
    return 0


def cmd_probe_activate(args) -> int:
    _ensure_bottles_closed()
    _storage, bottle = _find_bottle(args.bottle)
    status = probe_status(bottle)
    if status.baseline_ok:
        raise DgVoodooError(
            "La probe è ancora alla baseline: installa dgVoodoo2 con probe-install prima dell'override."
        )
    result = activate_app_overrides(bottle, status.executable, ["ddraw"])
    observed = query_app_override(bottle, status.executable, "ddraw")
    if observed != "n,b":
        raise DgVoodooError(f"Override ddraw non verificato dopo activation: {observed!r}")
    print("[PASS] Wine AppDefaults per-app attivato.")
    print(f"Executable: {result.app_name}")
    print("Chiave: HKCU\\Software\\Wine\\AppDefaults\\" + result.app_name + "\\DllOverrides")
    print("ddraw = n,b (REG_SZ)")
    print("Override globale bottle: NON modificato")
    print("bottle.yml/user.reg: nessuna modifica diretta da RetroCD")
    return 0


def cmd_probe_override_tamper(args) -> int:
    _ensure_bottles_closed()
    _storage, bottle = _find_bottle(args.bottle)
    status = probe_status(bottle)
    message = override_tamper_refusal_test(bottle, status.executable, "ddraw")
    print("[PASS] Modified-override refusal verificato.")
    print(f"Rifiuto osservato: {message}")
    print("ddraw è stato riportato a n,b; la transazione AppDefaults resta attiva.")
    return 0


def cmd_probe_deactivate(args) -> int:
    _ensure_bottles_closed()
    _storage, bottle = _find_bottle(args.bottle)
    status = probe_status(bottle)
    result = deactivate_app_overrides(bottle, status.executable)
    observed = query_app_override(bottle, status.executable, "ddraw")
    if observed is not None:
        raise DgVoodooError(f"Override ddraw residuo dopo restore: {observed!r}")
    print("[PASS] Wine AppDefaults per-app ripristinato.")
    print(f"Executable: {result.app_name}")
    print("ddraw: assente come nella baseline iniziale")
    print("Stato transazione RetroCD: rimosso")
    return 0


def cmd_probe_uninstall(args) -> int:
    _ensure_bottles_closed()
    _storage, bottle = _find_bottle(args.bottle)
    before = probe_status(bottle)
    activation = activation_status(bottle, before.executable)
    if activation.state != "inactive":
        raise DgVoodooError(
            f"Override Wine ancora {activation.state}: esegui probe-deactivate prima dell'uninstall."
        )
    status = uninstall_probe(bottle)
    print("[PASS] Uninstall/restore dgVoodoo2 completato.")
    print(f"Probe: {status.root}")
    print("Baseline byte-for-byte: PASS")
    print("DDraw.dll originale ripristinata; dgVoodoo.conf e unrelated.bin invariati.")
    return 0


def cmd_probe_clean(args) -> int:
    _ensure_bottles_closed()
    _storage, bottle = _find_bottle(args.bottle)
    status = probe_status(bottle)
    activation = activation_status(bottle, status.executable)
    if activation.state != "inactive":
        raise DgVoodooError(
            f"Override Wine ancora {activation.state}: cleanup rifiutato."
        )
    clean_probe(bottle)
    print("[PASS] Directory probe rimossa completamente.")
    print("Cleanup consentito solo dopo baseline byte-for-byte valida e senza file inattesi.")
    return 0


def parser() -> argparse.ArgumentParser:
    out = argparse.ArgumentParser(
        description="Diagnostica e probe isolata del manager dgVoodoo2 di Bottles RetroCD."
    )
    sub = out.add_subparsers(dest="command", required=True)

    inv = sub.add_parser("inventory", help="Elenca bottle private e metadata release ufficiale.")
    inv.set_defaults(func=cmd_inventory)

    inspect = sub.add_parser("inspect", help="Valida un executable dentro una bottle e rileva x86/x64.")
    inspect.add_argument("--bottle", required=True, help="Nome esatto della bottle Bottles.")
    inspect.add_argument(
        "--executable",
        required=True,
        help="Percorso assoluto o relativo a drive_c dell'executable Windows.",
    )
    inspect.set_defaults(func=cmd_inspect)

    probe_prepare = sub.add_parser(
        "probe-prepare",
        help="Crea una fixture x86 non-gioco confinata in C:\\RetroCD-dgVoodoo-Probe.",
    )
    probe_prepare.add_argument("--bottle", required=True)
    probe_prepare.set_defaults(func=cmd_probe_prepare)

    probe_status_p = sub.add_parser("probe-status", help="Mostra lo stato/hash della probe.")
    probe_status_p.add_argument("--bottle", required=True)
    probe_status_p.set_defaults(func=cmd_probe_status)

    probe_install_p = sub.add_parser(
        "probe-install",
        help="Scarica/verifica la release ufficiale e installa solo DDraw x86 nella probe.",
    )
    probe_install_p.add_argument("--bottle", required=True)
    probe_install_p.set_defaults(func=cmd_probe_install)

    probe_tamper_p = sub.add_parser(
        "probe-tamper-test",
        help="Verifica che una DLL gestita modificata blocchi l'uninstall automatico.",
    )
    probe_tamper_p.add_argument("--bottle", required=True)
    probe_tamper_p.set_defaults(func=cmd_probe_tamper)

    probe_activate_p = sub.add_parser(
        "probe-activate",
        help="Attiva ddraw=n,b via Wine AppDefaults solo per l'executable probe.",
    )
    probe_activate_p.add_argument("--bottle", required=True)
    probe_activate_p.set_defaults(func=cmd_probe_activate)

    probe_override_tamper_p = sub.add_parser(
        "probe-override-tamper-test",
        help="Verifica che un AppDefaults modificato blocchi il restore automatico.",
    )
    probe_override_tamper_p.add_argument("--bottle", required=True)
    probe_override_tamper_p.set_defaults(func=cmd_probe_override_tamper)

    probe_deactivate_p = sub.add_parser(
        "probe-deactivate",
        help="Ripristina il precedente AppDefaults per l'executable probe.",
    )
    probe_deactivate_p.add_argument("--bottle", required=True)
    probe_deactivate_p.set_defaults(func=cmd_probe_deactivate)

    probe_uninstall_p = sub.add_parser(
        "probe-uninstall",
        help="Disinstalla la probe e verifica il restore byte-for-byte.",
    )
    probe_uninstall_p.add_argument("--bottle", required=True)
    probe_uninstall_p.set_defaults(func=cmd_probe_uninstall)

    probe_clean_p = sub.add_parser(
        "probe-clean",
        help="Rimuove la directory probe solo se è tornata alla baseline ed è priva di file inattesi.",
    )
    probe_clean_p.add_argument("--bottle", required=True)
    probe_clean_p.set_defaults(func=cmd_probe_clean)
    return out


def main() -> int:
    args = parser().parse_args()
    try:
        return int(args.func(args))
    except DgVoodooError as exc:
        print(f"[FAIL] {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
