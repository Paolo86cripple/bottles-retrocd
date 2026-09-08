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
    print(f"Probe: {status.root}")
    print(f"Executable: {status.executable}")
    print(f"Baseline: {'PASS' if status.baseline_ok else 'MODIFICATA/INSTALLATA'}")
    print(f"DDraw SHA-256: {status.ddraw_sha256}")
    print(f"Config SHA-256: {status.config_sha256}")
    print(f"Unrelated SHA-256: {status.unrelated_sha256}")
    return 0


def cmd_probe_install(args) -> int:
    _storage, bottle = _find_bottle(args.bottle)
    result = install_probe(bottle)
    print(f"[PASS] dgVoodoo2 {result.release.version} installato nella sola probe.")
    print(f"Archivio verificato: {result.archive}")
    print(f"SHA-256 ufficiale: {result.release.sha256}")
    print(f"Manifest: {result.report.manifest_path}")
    print("Wrapper: DDraw.dll x86")
    print("dgVoodoo.conf preesistente: preservato")
    print("unrelated.bin: invariato")
    print(f"Wine override PREVIEW soltanto: ddraw=n,b")
    print("Nessun override Wine applicato in questa fase.")
    return 0


def cmd_probe_tamper(args) -> int:
    _storage, bottle = _find_bottle(args.bottle)
    message = tamper_refusal_probe(bottle)
    print("[PASS] Modified-file refusal verificato.")
    print(f"Rifiuto osservato: {message}")
    print("La DLL gestita è stata ripristinata ai byte installati; l'installazione probe resta valida.")
    return 0


def cmd_probe_uninstall(args) -> int:
    _storage, bottle = _find_bottle(args.bottle)
    status = uninstall_probe(bottle)
    print("[PASS] Uninstall/restore dgVoodoo2 completato.")
    print(f"Probe: {status.root}")
    print("Baseline byte-for-byte: PASS")
    print("DDraw.dll originale ripristinata; dgVoodoo.conf e unrelated.bin invariati.")
    return 0


def cmd_probe_clean(args) -> int:
    _storage, bottle = _find_bottle(args.bottle)
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
