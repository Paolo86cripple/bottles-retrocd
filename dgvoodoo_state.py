#!/usr/bin/env python3
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from dgvoodoo_backend import (
    BottleInfo,
    DgVoodooError,
    SCHEMA_VERSION,
    Wrapper,
    manager_data_dir,
    sha256_file,
    validate_game_target,
)

MAX_INSTALLATIONS = 4096
MAX_MANIFEST_BYTES = 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class InstallationState:
    state: str
    target_exe: Path
    arch: str
    version: str = ""
    wrappers: tuple[Wrapper, ...] = ()
    wine_overrides: str = ""
    manifest_path: Path | None = None
    managed_files: tuple[Path, ...] = ()
    preserved_files: tuple[Path, ...] = ()
    control_panel: Path | None = None
    problems: tuple[str, ...] = ()

    @property
    def active_payload(self) -> bool:
        return self.state in {"installed", "modified"}


def _load_manifest(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise DgVoodooError(f"Manifest dgVoodoo2 non regolare: {path}")
    try:
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            raise DgVoodooError(f"Manifest dgVoodoo2 troppo grande: {path}")
        raw = json.loads(path.read_text(encoding="utf-8"))
    except DgVoodooError:
        raise
    except (OSError, json.JSONDecodeError) as exc:
        raise DgVoodooError(f"Manifest dgVoodoo2 non leggibile: {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("schema_version") != SCHEMA_VERSION:
        raise DgVoodooError(f"Manifest dgVoodoo2 con schema non supportato: {path}")
    return raw


def _matching_manifest(
    data_root: Path,
    bottle: BottleInfo,
    executable: Path,
) -> tuple[Path, dict] | None:
    installs = data_root / "installations"
    if not installs.exists():
        return None
    if installs.is_symlink() or not installs.is_dir():
        raise DgVoodooError(f"Directory installazioni dgVoodoo2 non regolare: {installs}")
    try:
        entries = list(installs.iterdir())
    except OSError as exc:
        raise DgVoodooError(f"Impossibile leggere {installs}: {exc}") from exc
    if len(entries) > MAX_INSTALLATIONS:
        raise DgVoodooError(
            f"Troppe installazioni dgVoodoo2 ({len(entries)} > {MAX_INSTALLATIONS}); stato rifiutato."
        )

    exe_s = str(executable.resolve())
    bottle_s = str(bottle.root.resolve())
    matches: list[tuple[Path, dict]] = []
    for entry in entries:
        if entry.is_symlink() or not entry.is_dir():
            continue
        manifest_path = entry / "manifest.json"
        if not manifest_path.is_file() or manifest_path.is_symlink():
            continue
        manifest = _load_manifest(manifest_path)
        bottle_data = manifest.get("bottle")
        if not isinstance(bottle_data, dict):
            continue
        if manifest.get("target_exe") == exe_s and bottle_data.get("root") == bottle_s:
            matches.append((manifest_path, manifest))
    if len(matches) > 1:
        raise DgVoodooError(
            f"Più manifest dgVoodoo2 appartengono allo stesso executable ({len(matches)}); stato ambiguo."
        )
    return matches[0] if matches else None


def inspect_installation(
    bottle: BottleInfo,
    executable: Path,
    *,
    data_root: Path | None = None,
) -> InstallationState:
    exe, detected_arch = validate_game_target(executable, bottle)
    root = (data_root or manager_data_dir()).resolve(strict=False)
    match = _matching_manifest(root, bottle, exe)
    if match is None:
        return InstallationState("inactive", exe, detected_arch.value)

    manifest_path, manifest = match
    problems: list[str] = []

    target_dir_raw = manifest.get("target_dir")
    if not isinstance(target_dir_raw, str):
        raise DgVoodooError("Manifest dgVoodoo2 senza target_dir valido.")
    target_dir = Path(target_dir_raw).resolve(strict=False)
    if target_dir != exe.parent.resolve(strict=True):
        raise DgVoodooError("Directory target dgVoodoo2 diversa dall'executable selezionato.")

    arch = manifest.get("arch")
    if arch != detected_arch.value:
        problems.append(
            f"architettura manifest={arch!r}, PE attuale={detected_arch.value!r}"
        )

    release = manifest.get("release")
    if not isinstance(release, dict) or not isinstance(release.get("version"), str):
        raise DgVoodooError("Manifest dgVoodoo2 senza release/version valida.")
    version = release["version"]

    wrappers_raw = manifest.get("wrappers")
    if not isinstance(wrappers_raw, list) or not wrappers_raw:
        raise DgVoodooError("Manifest dgVoodoo2 senza wrapper validi.")
    try:
        wrappers = tuple(Wrapper(item) for item in wrappers_raw)
    except (ValueError, TypeError) as exc:
        raise DgVoodooError("Manifest dgVoodoo2 contiene wrapper sconosciuti.") from exc
    if len(wrappers) != len(set(wrappers)):
        raise DgVoodooError("Manifest dgVoodoo2 contiene wrapper duplicati.")

    wine_overrides = manifest.get("wine_overrides")
    if not isinstance(wine_overrides, str):
        raise DgVoodooError("Manifest dgVoodoo2 senza wine_overrides valido.")

    managed = manifest.get("managed_files")
    if not isinstance(managed, list) or not managed:
        raise DgVoodooError("Manifest dgVoodoo2 senza file gestiti.")
    managed_files: list[Path] = []
    control_panel: Path | None = None
    install_dir = manifest_path.parent.resolve(strict=True)
    for item in managed:
        if not isinstance(item, dict):
            raise DgVoodooError("Voce managed_files dgVoodoo2 non valida.")
        name = item.get("name")
        expected = item.get("installed_sha256")
        if not isinstance(name, str) or Path(name).name != name:
            raise DgVoodooError(f"Nome file gestito dgVoodoo2 non valido: {name!r}")
        if not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected):
            raise DgVoodooError(f"Hash file gestito dgVoodoo2 non valido: {name}")
        dest = target_dir / name
        managed_files.append(dest)
        if name.casefold() == "dgvoodoocpl.exe":
            control_panel = dest
        if dest.is_symlink() or not dest.is_file():
            problems.append(f"file gestito mancante/non regolare: {dest}")
        else:
            try:
                if sha256_file(dest) != expected:
                    problems.append(f"file gestito modificato: {dest}")
            except OSError as exc:
                problems.append(f"file gestito non leggibile: {dest}: {exc}")

        backup_raw = item.get("backup", "")
        if backup_raw:
            if not isinstance(backup_raw, str):
                raise DgVoodooError(f"Backup manifest non valido per {name}.")
            backup = (install_dir / backup_raw).resolve(strict=False)
            original_sha = item.get("original_sha256")
            if (
                not backup.is_relative_to(install_dir)
                or backup.is_symlink()
                or not backup.is_file()
                or not isinstance(original_sha, str)
                or not _SHA256_RE.fullmatch(original_sha)
            ):
                problems.append(f"backup non valido per {name}: {backup}")
            else:
                try:
                    if sha256_file(backup) != original_sha:
                        problems.append(f"backup corrotto per {name}: {backup}")
                except OSError as exc:
                    problems.append(f"backup non leggibile per {name}: {exc}")

    preserved_raw = manifest.get("preserved_files", [])
    if not isinstance(preserved_raw, list) or not all(isinstance(x, str) for x in preserved_raw):
        raise DgVoodooError("Manifest dgVoodoo2 con preserved_files non valido.")
    preserved_files = tuple(target_dir / name for name in preserved_raw)

    state = "modified" if problems else "installed"
    return InstallationState(
        state=state,
        target_exe=exe,
        arch=detected_arch.value,
        version=version,
        wrappers=wrappers,
        wine_overrides=wine_overrides,
        manifest_path=manifest_path,
        managed_files=tuple(managed_files),
        preserved_files=preserved_files,
        control_panel=control_panel,
        problems=tuple(problems),
    )
