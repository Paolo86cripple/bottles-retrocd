#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from bottles_storage import discover_bottles
from dgvoodoo_backend import (
    DgVoodooError,
    fetch_latest_release,
    validate_game_target,
)
from sandbox_backend import INSTANCE, SandboxBackend


def _bottles():
    sandbox = SandboxBackend(INSTANCE)
    storage, bottles = discover_bottles(sandbox.private_home)
    return sandbox, storage, bottles


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
    _sandbox, storage, bottles = _bottles()
    bottle = next((item for item in bottles if item.name == args.bottle), None)
    if bottle is None:
        names = ", ".join(item.name for item in bottles) or "nessuna"
        raise DgVoodooError(
            f"Bottle {args.bottle!r} non trovata in {storage.root}. Disponibili: {names}"
        )
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


def parser() -> argparse.ArgumentParser:
    out = argparse.ArgumentParser(
        description="Diagnostica read-only del manager dgVoodoo2 di Bottles RetroCD."
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
