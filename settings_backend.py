#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

from display_backend import DISPLAY_AUTO, normalize_display_backend

SCHEMA_VERSION = 1


def config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "bottles-retro-cd"


def config_path() -> Path:
    return config_dir() / "config.toml"


def load_settings() -> dict:
    defaults = {
        "schema_version": SCHEMA_VERSION,
        "gpu_pci": "",
        "display_backend": DISPLAY_AUTO,
    }
    path = config_path()
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return defaults
    if not isinstance(raw, dict):
        return defaults
    out = defaults.copy()
    if isinstance(raw.get("gpu_pci"), str):
        out["gpu_pci"] = raw["gpu_pci"]
    out["display_backend"] = normalize_display_backend(raw.get("display_backend"))
    return out


def save_settings(settings: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    gpu_pci = str(settings.get("gpu_pci", ""))
    display_backend = normalize_display_backend(settings.get("display_backend"))
    text = (
        f"schema_version = {SCHEMA_VERSION}\n"
        f"gpu_pci = {json.dumps(gpu_pci, ensure_ascii=False)}\n"
        f"display_backend = {json.dumps(display_backend, ensure_ascii=False)}\n"
    )
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path
