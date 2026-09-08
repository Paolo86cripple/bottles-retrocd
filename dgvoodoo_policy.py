#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from dgvoodoo_backend import BottleInfo, DgVoodooError, manager_data_dir, validate_game_target
from dgvoodoo_wine import (
    activate_app_overrides as _activate_app_overrides,
    activation_status,
    deactivate_app_overrides,
    query_app_override,
    tamper_refusal_test,
)

MAX_ACTIVATIONS = 4096
MAX_STATE_BYTES = 1024 * 1024


def ensure_unique_managed_app_name(
    bottle: BottleInfo,
    executable: Path,
    *,
    data_root: Path | None = None,
) -> None:
    """Reject two RetroCD activations sharing Wine's basename-only AppDefaults key."""
    exe, _arch = validate_game_target(executable, bottle)
    app_name = exe.name.casefold()
    root = (data_root or manager_data_dir()).resolve(strict=False)
    activations = root / "activations"
    if not activations.exists():
        return
    if activations.is_symlink() or not activations.is_dir():
        raise DgVoodooError(f"Directory attivazioni dgVoodoo2 non regolare: {activations}")
    try:
        entries = list(activations.iterdir())
    except OSError as exc:
        raise DgVoodooError(f"Impossibile leggere {activations}: {exc}") from exc
    if len(entries) > MAX_ACTIVATIONS:
        raise DgVoodooError(
            f"Troppe attivazioni dgVoodoo2 ({len(entries)} > {MAX_ACTIVATIONS}); controllo rifiutato."
        )

    bottle_root = str(bottle.root.resolve())
    target = str(exe.resolve())
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            continue
        state_path = entry / "state.json"
        if not state_path.is_file() or state_path.is_symlink():
            continue
        try:
            if state_path.stat().st_size > MAX_STATE_BYTES:
                raise DgVoodooError(f"Stato override troppo grande: {state_path}")
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except DgVoodooError:
            raise
        except (OSError, json.JSONDecodeError) as exc:
            raise DgVoodooError(f"Stato override non leggibile: {state_path}: {exc}") from exc
        if not isinstance(state, dict):
            raise DgVoodooError(f"Stato override non valido: {state_path}")
        if state.get("status") not in {"pending", "active"}:
            continue
        if state.get("bottle_root") != bottle_root:
            continue
        other_app = state.get("app_name")
        other_target = state.get("target_exe")
        if (
            isinstance(other_app, str)
            and other_app.casefold() == app_name
            and isinstance(other_target, str)
            and other_target != target
        ):
            raise DgVoodooError(
                "Wine AppDefaults identifica il programma solo per basename: "
                f"{exe.name!r} è già gestito nella stessa bottle per {other_target}. "
                "Una seconda attivazione con lo stesso basename è rifiutata."
            )


def activate_app_overrides(
    bottle: BottleInfo,
    executable: Path,
    overrides: Iterable[str],
    *,
    data_root: Path | None = None,
    runner=None,
):
    ensure_unique_managed_app_name(bottle, executable, data_root=data_root)
    kwargs = {"data_root": data_root}
    if runner is not None:
        kwargs["runner"] = runner
    return _activate_app_overrides(bottle, executable, overrides, **kwargs)


__all__ = [
    "activate_app_overrides",
    "activation_status",
    "deactivate_app_overrides",
    "ensure_unique_managed_app_name",
    "query_app_override",
    "tamper_refusal_test",
]
