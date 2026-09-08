#!/usr/bin/env python3
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from dgvoodoo_backend import BottleInfo, DgVoodooError

MAX_BOTTLE_ENTRIES = 4096


@dataclass(frozen=True, slots=True)
class BottlesStorage:
    root: Path
    source: str
    configured_custom: Path | None = None


def _default_root(private_home: Path) -> Path:
    return private_home / ".local" / "share" / "bottles" / "bottles"


def _data_file(private_home: Path) -> Path:
    return private_home / ".local" / "share" / "bottles" / "data.yml"


def _parse_simple_yaml_scalar(raw: str) -> str | None:
    value = raw.strip()
    if not value or value in {"null", "Null", "NULL", "~"}:
        return None
    if value.startswith('"'):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise DgVoodooError(f"custom_bottles_path con quoting non valido: {exc}") from exc
        if not isinstance(decoded, str):
            raise DgVoodooError("custom_bottles_path non è una stringa.")
        return decoded
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'"):
            raise DgVoodooError("custom_bottles_path con quoting YAML incompleto.")
        return value[1:-1].replace("''", "'")
    return value


def read_custom_bottles_path(private_home: Path) -> Path | None:
    data_file = _data_file(private_home)
    if not data_file.is_file():
        return None
    try:
        text = data_file.read_text(encoding="utf-8")
    except OSError as exc:
        raise DgVoodooError(f"Impossibile leggere {data_file}: {exc}") from exc

    matches: list[str | None] = []
    for raw_line in text.splitlines():
        line = raw_line.lstrip()
        if line.startswith("#") or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        if key.strip() == "custom_bottles_path":
            matches.append(_parse_simple_yaml_scalar(raw_value))
    if len(matches) > 1:
        raise DgVoodooError("data.yml contiene più custom_bottles_path; discovery rifiutata.")
    if not matches or matches[0] is None:
        return None

    candidate = Path(matches[0]).expanduser()
    if not candidate.is_absolute():
        raise DgVoodooError(f"custom_bottles_path relativo non ammesso: {candidate}")
    if "\x00" in str(candidate):
        raise DgVoodooError("custom_bottles_path contiene NUL.")
    return candidate


def resolve_bottles_storage(private_home: Path) -> BottlesStorage:
    private_home = private_home.resolve(strict=True)
    configured = read_custom_bottles_path(private_home)
    if configured is None:
        return BottlesStorage(_default_root(private_home), "default", None)

    try:
        root = configured.resolve(strict=True)
    except OSError as exc:
        raise DgVoodooError(
            f"custom_bottles_path configurato ma non accessibile: {configured}: {exc}"
        ) from exc
    if not root.is_dir():
        raise DgVoodooError(f"custom_bottles_path non è una directory: {root}")
    if root == Path("/"):
        raise DgVoodooError("custom_bottles_path '/' rifiutato per sicurezza.")
    return BottlesStorage(root, "custom", configured)


def discover_bottles(private_home: Path) -> tuple[BottlesStorage, tuple[BottleInfo, ...]]:
    storage = resolve_bottles_storage(private_home)
    root = storage.root
    if not root.is_dir():
        return storage, ()

    out: list[BottleInfo] = []
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        raise DgVoodooError(f"Impossibile leggere root bottle {root}: {exc}") from exc
    if len(entries) > MAX_BOTTLE_ENTRIES:
        raise DgVoodooError(
            f"Root bottle con troppi elementi ({len(entries)} > {MAX_BOTTLE_ENTRIES}); discovery rifiutata."
        )

    for child in sorted(entries, key=lambda p: p.name.casefold()):
        if child.is_symlink() or not child.is_dir():
            continue
        config = child / "bottle.yml"
        drive = child / "drive_c"
        if (
            config.is_file()
            and not config.is_symlink()
            and drive.is_dir()
            and not drive.is_symlink()
        ):
            out.append(BottleInfo(child.name, child.resolve(), drive.resolve()))
    return storage, tuple(out)
