#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from display_backend import (
    DisplayBackend,
    bottles_tool_command,
    diagnose_output,
    wayland_session_available,
)
from sandbox_backend import INSTANCE, SandboxBackend


TOOLS = ("winecfg", "regedit", "taskmgr", "control", "explorer")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Probe grafica non-game per confrontare Wine XWayland e Wayland nativo "
            "dentro la stessa istanza Bubblejail/Bottles."
        )
    )
    parser.add_argument("--bottle", required=True)
    parser.add_argument("--backend", choices=[item.value for item in DisplayBackend], required=True)
    parser.add_argument("--tool", choices=TOOLS, default="winecfg")
    parser.add_argument("--instance", default=INSTANCE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    backend = DisplayBackend(args.backend)
    sandbox = SandboxBackend(args.instance)
    if sandbox.running():
        print("[FAIL] Chiudi Bottles/Bubblejail prima del probe display.", file=sys.stderr)
        return 2
    if backend is DisplayBackend.WAYLAND and not wayland_session_available(os.environ):
        print(
            "[FAIL] Sessione Wayland host non rilevata: WAYLAND_DISPLAY/XDG_RUNTIME_DIR mancanti.",
            file=sys.stderr,
        )
        return 2

    command = bottles_tool_command(
        args.instance,
        args.bottle,
        args.tool,
        backend=backend,
    )
    print(f"[INFO] Backend richiesto: {backend.value}")
    print(f"[INFO] Tool non-game: {args.tool}")
    if backend is DisplayBackend.WAYLAND:
        print("[INFO] DISPLAY rimosso solo dal processo figlio; nessuna modifica a services.toml/IPC/rete.")
    else:
        print("[INFO] DISPLAY ereditato: percorso Wine X11/XWayland invariato.")
    print("[INFO] Se compare una finestra, chiudila normalmente per completare il probe.")

    try:
        proc = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except FileNotFoundError as exc:
        print(f"[FAIL] Comando non trovato: {exc.filename}", file=sys.stderr)
        return 2

    output = proc.stdout or ""
    if output:
        print("\n--- output Bubblejail/Bottles/Wine ---")
        print(output.rstrip())
        print("--- fine output ---")

    diag = diagnose_output(output, backend=backend)
    if diag.mit_shm_error:
        print("[FAIL] Rilevato errore MIT-SHM/XWayland.")
        return 3
    if backend is DisplayBackend.WAYLAND and diag.wayland_driver_seen:
        print("[PASS] winewayland.drv osservato; nessun errore MIT-SHM rilevato.")
    elif backend is DisplayBackend.WAYLAND:
        print("[INFO] Nessun errore MIT-SHM; il log non contiene un marker winewayland.drv esplicito.")
    else:
        print("[INFO] Nessun pattern MIT-SHM rilevato in questo tool XWayland.")
    print(f"[INFO] Exit code trasporto: {proc.returncode} (la visibilità della finestra va confermata dall'utente).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
