#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import struct
from dataclasses import dataclass
from pathlib import Path

from dgvoodoo_backend import (
    BottleInfo,
    DgVoodooError,
    InstallReport,
    ReleaseInfo,
    Wrapper,
    download_release,
    fetch_latest_release,
    install_wrappers,
    sha256_file,
    uninstall_wrappers,
    validate_game_target,
)

PROBE_SCHEMA_VERSION = 1
PROBE_DIR_NAME = "RetroCD-dgVoodoo-Probe"
PROBE_EXE_NAME = "retrocd-dgvoodoo-probe.exe"
PROBE_STATE_NAME = ".retrocd-dgvoodoo-probe.json"
PROBE_DDRAW_NAME = "DDraw.dll"
PROBE_CONFIG_NAME = "dgVoodoo.conf"
PROBE_UNRELATED_NAME = "unrelated.bin"

_ORIGINAL_DDRAW = b"RetroCD dgVoodoo2 probe: original DDraw placeholder\n"
_ORIGINAL_CONFIG = b"# RetroCD dgVoodoo2 probe: pre-existing config\n"
_UNRELATED = b"RetroCD dgVoodoo2 probe: unrelated sentinel\n"


@dataclass(frozen=True, slots=True)
class ProbeStatus:
    root: Path
    executable: Path
    baseline_ok: bool
    ddraw_sha256: str
    config_sha256: str
    unrelated_sha256: str


@dataclass(frozen=True, slots=True)
class ProbeInstallResult:
    release: ReleaseInfo
    archive: Path
    report: InstallReport


def probe_root(bottle: BottleInfo) -> Path:
    return bottle.drive_c / PROBE_DIR_NAME


def probe_executable(bottle: BottleInfo) -> Path:
    return probe_root(bottle) / PROBE_EXE_NAME


def _minimal_x86_pe() -> bytes:
    data = bytearray(256)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, 0x80)
    data[0x80:0x84] = b"PE\x00\x00"
    struct.pack_into("<H", data, 0x84, 0x014C)
    return bytes(data)


def _write_new(path: Path, data: bytes, mode: int = 0o644) -> None:
    if path.exists() or path.is_symlink():
        raise DgVoodooError(f"Probe: file già esistente, rifiuto overwrite: {path}")
    with path.open("xb") as fh:
        fh.write(data)
    os.chmod(path, mode)


def _state_path(bottle: BottleInfo) -> Path:
    return probe_root(bottle) / PROBE_STATE_NAME


def _read_state(bottle: BottleInfo) -> dict:
    root = probe_root(bottle)
    state_path = _state_path(bottle)
    if root.is_symlink() or not root.is_dir():
        raise DgVoodooError(f"Probe dgVoodoo2 assente/non regolare: {root}")
    if state_path.is_symlink() or not state_path.is_file():
        raise DgVoodooError(f"Stato probe dgVoodoo2 assente/non regolare: {state_path}")
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DgVoodooError(f"Stato probe dgVoodoo2 non leggibile: {exc}") from exc
    if not isinstance(state, dict) or state.get("schema_version") != PROBE_SCHEMA_VERSION:
        raise DgVoodooError("Stato probe dgVoodoo2 con schema non supportato.")
    if state.get("bottle_root") != str(bottle.root.resolve()):
        raise DgVoodooError("Stato probe dgVoodoo2 appartiene a una bottle diversa.")
    if state.get("probe_root") != str(root.resolve()):
        raise DgVoodooError("Stato probe dgVoodoo2 appartiene a una directory diversa.")
    hashes = state.get("baseline_sha256")
    if not isinstance(hashes, dict):
        raise DgVoodooError("Stato probe dgVoodoo2 senza hash baseline.")
    for name in (PROBE_DDRAW_NAME, PROBE_CONFIG_NAME, PROBE_UNRELATED_NAME):
        value = hashes.get(name)
        if not isinstance(value, str) or len(value) != 64:
            raise DgVoodooError(f"Hash baseline probe non valido per {name}.")
    return state


def prepare_probe(bottle: BottleInfo) -> ProbeStatus:
    drive = bottle.drive_c.resolve(strict=True)
    if bottle.drive_c.is_symlink() or not drive.is_dir():
        raise DgVoodooError(f"drive_c non regolare per la probe: {bottle.drive_c}")
    root = probe_root(bottle)
    if root.exists() or root.is_symlink():
        raise DgVoodooError(
            f"Directory probe già esistente: {root}. Usa i comandi probe status/uninstall/clean; non viene sovrascritta."
        )
    root.mkdir(mode=0o755)
    try:
        _write_new(root / PROBE_EXE_NAME, _minimal_x86_pe())
        _write_new(root / PROBE_DDRAW_NAME, _ORIGINAL_DDRAW)
        _write_new(root / PROBE_CONFIG_NAME, _ORIGINAL_CONFIG)
        _write_new(root / PROBE_UNRELATED_NAME, _UNRELATED)
        hashes = {
            PROBE_DDRAW_NAME: sha256_file(root / PROBE_DDRAW_NAME),
            PROBE_CONFIG_NAME: sha256_file(root / PROBE_CONFIG_NAME),
            PROBE_UNRELATED_NAME: sha256_file(root / PROBE_UNRELATED_NAME),
        }
        state = {
            "schema_version": PROBE_SCHEMA_VERSION,
            "bottle_name": bottle.name,
            "bottle_root": str(bottle.root.resolve()),
            "probe_root": str(root.resolve()),
            "executable": PROBE_EXE_NAME,
            "baseline_sha256": hashes,
        }
        state_path = root / PROBE_STATE_NAME
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(state_path, 0o600)
    except Exception:
        for child in root.iterdir() if root.is_dir() else ():
            try:
                child.unlink()
            except OSError:
                pass
        try:
            root.rmdir()
        except OSError:
            pass
        raise

    exe, arch = validate_game_target(root / PROBE_EXE_NAME, bottle)
    if arch.value != "x86":
        raise DgVoodooError(f"Probe interna inattesa: architettura {arch.value} invece di x86.")
    return probe_status(bottle)


def probe_status(bottle: BottleInfo) -> ProbeStatus:
    state = _read_state(bottle)
    root = probe_root(bottle).resolve(strict=True)
    exe = root / PROBE_EXE_NAME
    validate_game_target(exe, bottle)
    hashes = state["baseline_sha256"]

    actual: dict[str, str] = {}
    baseline_ok = True
    for name in (PROBE_DDRAW_NAME, PROBE_CONFIG_NAME, PROBE_UNRELATED_NAME):
        path = root / name
        if path.is_symlink() or not path.is_file():
            actual[name] = "missing"
            baseline_ok = False
            continue
        actual[name] = sha256_file(path)
        if actual[name] != hashes[name]:
            baseline_ok = False
    return ProbeStatus(
        root=root,
        executable=exe,
        baseline_ok=baseline_ok,
        ddraw_sha256=actual[PROBE_DDRAW_NAME],
        config_sha256=actual[PROBE_CONFIG_NAME],
        unrelated_sha256=actual[PROBE_UNRELATED_NAME],
    )


def install_probe_from_archive(
    bottle: BottleInfo,
    release: ReleaseInfo,
    archive: Path,
) -> InstallReport:
    before = probe_status(bottle)
    if not before.baseline_ok:
        raise DgVoodooError("Probe non è nella baseline iniziale; installazione rifiutata.")
    state = _read_state(bottle)
    baseline = state["baseline_sha256"]
    report = install_wrappers(
        archive,
        release,
        bottle,
        before.executable,
        [Wrapper.DDRAW],
        include_control_panel=True,
        preserve_existing_config=True,
    )
    root = before.root
    try:
        if sha256_file(root / PROBE_DDRAW_NAME) == baseline[PROBE_DDRAW_NAME]:
            raise DgVoodooError("Probe: DDraw.dll non è stata sostituita dall'installazione.")
        if sha256_file(root / PROBE_CONFIG_NAME) != baseline[PROBE_CONFIG_NAME]:
            raise DgVoodooError("Probe: dgVoodoo.conf preesistente è stato modificato.")
        if sha256_file(root / PROBE_UNRELATED_NAME) != baseline[PROBE_UNRELATED_NAME]:
            raise DgVoodooError("Probe: file unrelated è stato modificato.")
        cpl = root / "dgVoodooCpl.exe"
        if cpl.is_symlink() or not cpl.is_file():
            raise DgVoodooError("Probe: dgVoodooCpl.exe non installato correttamente.")
    except Exception:
        try:
            uninstall_wrappers(bottle, before.executable)
        except Exception:
            pass
        raise
    return report


def install_probe(bottle: BottleInfo) -> ProbeInstallResult:
    release = fetch_latest_release()
    archive = download_release(release)
    report = install_probe_from_archive(bottle, release, archive)
    return ProbeInstallResult(release=release, archive=archive, report=report)


def tamper_refusal_probe(bottle: BottleInfo) -> str:
    status = probe_status(bottle)
    ddraw = status.root / PROBE_DDRAW_NAME
    if ddraw.is_symlink() or not ddraw.is_file():
        raise DgVoodooError("Probe: DDraw.dll gestita assente/non regolare.")
    installed = ddraw.read_bytes()
    ddraw.write_bytes(installed + b"\nRETROCD-TAMPER-TEST\n")
    try:
        try:
            uninstall_wrappers(bottle, status.executable)
        except DgVoodooError as exc:
            message = str(exc)
            if "modificato dopo" not in message:
                raise DgVoodooError(
                    f"Probe: uninstall ha fallito per un motivo inatteso durante tamper test: {message}"
                ) from exc
        else:
            raise DgVoodooError("Probe: ERRORE, uninstall ha accettato una DLL gestita modificata.")
    finally:
        ddraw.write_bytes(installed)
    return message


def uninstall_probe(bottle: BottleInfo) -> ProbeStatus:
    before = probe_status(bottle)
    restored = uninstall_wrappers(bottle, before.executable)
    if not restored:
        raise DgVoodooError("Probe: uninstall non ha ripristinato alcun file.")
    after = probe_status(bottle)
    if not after.baseline_ok:
        raise DgVoodooError("Probe: baseline non ripristinata byte-for-byte dopo uninstall.")
    if (after.root / "dgVoodooCpl.exe").exists():
        raise DgVoodooError("Probe: dgVoodooCpl.exe residuo dopo uninstall.")
    return after


def clean_probe(bottle: BottleInfo) -> None:
    status = probe_status(bottle)
    if not status.baseline_ok:
        raise DgVoodooError("Probe modificata/non ripristinata: cleanup automatico rifiutato.")
    root = status.root
    expected = {
        PROBE_EXE_NAME,
        PROBE_STATE_NAME,
        PROBE_DDRAW_NAME,
        PROBE_CONFIG_NAME,
        PROBE_UNRELATED_NAME,
    }
    actual = {item.name for item in root.iterdir()}
    if actual != expected:
        extra = ", ".join(sorted(actual - expected)) or "—"
        missing = ", ".join(sorted(expected - actual)) or "—"
        raise DgVoodooError(
            f"Probe contiene elementi inattesi/mancanti; cleanup rifiutato. extra={extra} missing={missing}"
        )
    for name in expected:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise DgVoodooError(f"Probe cleanup: elemento non regolare: {path}")
    for name in expected:
        (root / name).unlink()
    root.rmdir()
