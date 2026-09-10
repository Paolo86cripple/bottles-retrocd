#!/usr/bin/env python3
from __future__ import annotations

import getpass
import json
import os
import tomllib
from pathlib import Path

from display_backend import DISPLAY_AUTO, normalize_display_backend

SCHEMA_VERSION = 2


def config_dir() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "bottles-retro-cd"


def config_path() -> Path:
    return config_dir() / "config.toml"


def normalize_archive_root(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    return str(Path(os.path.abspath(os.path.expanduser(value.strip()))).resolve(strict=False))


def _legacy_archive_root() -> str:
    explicit = normalize_archive_root(os.environ.get("BOTTLES_RETRO_CD_ARCHIVE_ROOT", ""))
    if explicit:
        return explicit

    data_override = os.environ.get("BOTTLES_RETRO_CD_DATA_ROOT", "").strip()
    if data_override:
        candidate = Path(os.path.abspath(os.path.expanduser(data_override))) / "Downloads" / "retropc"
    else:
        candidate = Path("/run/media") / getpass.getuser() / "Data" / "Downloads" / "retropc"
    return str(candidate.resolve(strict=False)) if candidate.is_dir() else ""


def load_settings() -> dict:
    defaults = {
        "schema_version": SCHEMA_VERSION,
        "gpu_pci": "",
        "display_backend": DISPLAY_AUTO,
        "archive_root": _legacy_archive_root(),
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
    if isinstance(raw.get("archive_root"), str):
        out["archive_root"] = normalize_archive_root(raw.get("archive_root"))
    return out


def save_settings(settings: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    gpu_pci = str(settings.get("gpu_pci", ""))
    display_backend = normalize_display_backend(settings.get("display_backend"))
    archive_root = normalize_archive_root(settings.get("archive_root", ""))
    text = (
        f"schema_version = {SCHEMA_VERSION}\n"
        f"gpu_pci = {json.dumps(gpu_pci, ensure_ascii=False)}\n"
        f"display_backend = {json.dumps(display_backend, ensure_ascii=False)}\n"
        f"archive_root = {json.dumps(archive_root, ensure_ascii=False)}\n"
    )
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def migrate_legacy_archive_root() -> str:
    """Persist the old target-machine archive location without moving any dump.

    Existing valid configs are upgraded in-place only when they do not yet have
    ``archive_root``. Malformed configs are never overwritten automatically.
    """
    path = config_path()
    if path.exists():
        try:
            with path.open("rb") as fh:
                raw = tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError):
            return str(load_settings().get("archive_root", ""))
        if not isinstance(raw, dict):
            return str(load_settings().get("archive_root", ""))
        if "archive_root" in raw:
            return normalize_archive_root(raw.get("archive_root"))

    settings = load_settings()
    archive_root = normalize_archive_root(settings.get("archive_root", ""))
    if archive_root:
        settings["archive_root"] = archive_root
        save_settings(settings)
    return archive_root
