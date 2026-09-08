#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
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
            "Probe grafica non-game per confrontare Wine XWayland host, Wayland nativo "
            "e XWayland interno Gamescope nella stessa istanza Bubblejail/Bottles."
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
    if backend in {DisplayBackend.WAYLAND, DisplayBackend.GAMESCOPE_XWAYLAND}:
        if not wayland_session_available(os.environ):
            print(
                "[FAIL] Sessione Wayland host non rilevata: WAYLAND_DISPLAY/XDG_RUNTIME_DIR mancanti.",
                file=sys.stderr,
            )
            return 2
    if backend is DisplayBackend.GAMESCOPE_XWAYLAND:
        missing = [name for name in ("gamescope", "gamescopereaper") if shutil.which(name) is None]
        if missing:
            print("[FAIL] Componente Gamescope mancante: " + ", ".join(missing), file=sys.stderr)
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
        print("[INFO] Wine Wayland nativo: DISPLAY rimosso solo dal processo figlio.")
    elif backend is DisplayBackend.GAMESCOPE_XWAYLAND:
        print(
            "[INFO] XWayland interno Gamescope: 1920x1080 1:1, un solo XWayland, "
            "nessun upscaler/limiter/HDR/VRR/MangoApp/Steam mode."
        )
        print("[INFO] CAP_SYS_NICE non viene concessa: nessuna capability aggiuntiva alla jail.")
    else:
        print("[INFO] XWayland host: DISPLAY ereditato, percorso legacy invariato.")
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

    if backend is DisplayBackend.WAYLAND:
        if diag.wayland_driver_seen:
            print("[PASS] winewayland.drv osservato; nessun errore MIT-SHM rilevato.")
        else:
            print("[INFO] Nessun MIT-SHM; nessun marker winewayland.drv esplicito nel log.")
    elif backend is DisplayBackend.GAMESCOPE_XWAYLAND:
        if diag.gamescope_seen:
            print("[PASS] Gamescope/XWayland interno osservato; nessun errore MIT-SHM rilevato.")
        else:
            print("[INFO] Nessun MIT-SHM; marker Gamescope non osservato nel log.")
        if diag.gamescope_no_sys_nice:
            print(
                "[WARN] Gamescope non ha CAP_SYS_NICE: RetroCD non la concede intenzionalmente "
                "per non ampliare i privilegi della sandbox."
            )
    else:
        print("[INFO] Nessun pattern MIT-SHM rilevato nel percorso XWayland host.")

    print(f"[INFO] Exit code trasporto: {proc.returncode} (la visibilità della finestra va confermata dall'utente).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
