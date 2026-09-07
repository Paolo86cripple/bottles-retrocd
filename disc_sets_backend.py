#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from multidisc_backend import DiscEntry, DiscSet, disc_number, discover_disc_set
from settings_backend import config_dir

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class SavedDiscSet:
    set_id: str
    name: str
    discs: tuple[DiscEntry, ...]

    def to_disc_set(self) -> DiscSet:
        return DiscSet(self.set_id, self.discs, name=self.name, explicit=True)


def disc_sets_path() -> Path:
    return config_dir() / "disc-sets.toml"


def _safe_name(text: str) -> str:
    text = re.sub(r"(?i)(?<![a-z0-9])(?:disc|disk|cd)[\s_.-]*[0-9]{1,2}(?![0-9])", "", text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([)\]}])", r"\1", text)
    text = re.sub(r"([({[])\s+", r"\1", text)
    text = text.strip(" ._-()[]{}")
    return text or "Set multidisco"


def suggest_set_name(image: Path) -> str:
    # Redump/TOSEC names often repeat the complete title in both directory and
    # descriptor filename.  Prefer the descriptor stem and only remove the disc
    # ordinal; never alter the actual file or directory name.
    return _safe_name(image.stem)


def _set_id_for(name: str, discs: tuple[DiscEntry, ...]) -> str:
    seed = name.casefold() + "\n" + "\n".join(str(d.image) for d in discs)
    # Stable, filesystem/config friendly id without adding a crypto dependency.
    import hashlib

    slug = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")[:40] or "disc-set"
    return f"{slug}-{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:10]}"


def _validate_image(path: Path, root: Path) -> Path:
    try:
        image = path.expanduser().resolve(strict=True)
    except OSError as exc:
        raise RuntimeError(f"Immagine multidisco non accessibile: {path}: {exc}") from exc
    root_r = root.resolve(strict=False)
    if not image.is_file():
        raise RuntimeError(f"Il riferimento multidisco non è un file: {image}")
    if not image.is_relative_to(root_r):
        raise RuntimeError(f"Immagine multidisco fuori dalla directory autorizzata: {image}")
    return image


def make_saved_set(name: str, image_paths: list[Path], root: Path) -> SavedDiscSet:
    clean_name = name.strip() or "Set multidisco"
    by_number: dict[int, Path] = {}
    seen_paths: set[Path] = set()
    next_number = 1

    for raw in image_paths:
        image = _validate_image(raw, root)
        if image in seen_paths:
            continue
        seen_paths.add(image)
        number = disc_number(image)
        if number is None:
            while next_number in by_number:
                next_number += 1
            number = next_number
        if number in by_number and by_number[number] != image:
            raise RuntimeError(
                f"Due immagini risultano entrambe Disco {number}: {by_number[number]} e {image}"
            )
        by_number[number] = image
        next_number = max(next_number, number + 1)

    if not by_number:
        raise RuntimeError("Il set multidisco non contiene immagini.")

    discs = tuple(
        DiscEntry(number, image, f"Disco {number} · {image.relative_to(root.resolve(strict=False))}")
        for number, image in sorted(by_number.items())
    )
    return SavedDiscSet(_set_id_for(clean_name, discs), clean_name, discs)


def make_new_saved_set(selected: Path, root: Path) -> SavedDiscSet:
    """Create an explicit set containing only *selected*.

    Automatic grouping is intentionally ignored here: persisting archive
    metadata must be an explicit user action starting from the exact descriptor
    they selected (commonly Disc 1).
    """
    return make_saved_set(suggest_set_name(selected), [selected], root)

def load_saved_sets(root: Path) -> list[SavedDiscSet]:
    path = disc_sets_path()
    try:
        with path.open("rb") as fh:
            raw = tomllib.load(fh)
    except FileNotFoundError:
        return []
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise RuntimeError(f"Configurazione set multidisco non leggibile: {path}: {exc}") from exc

    if raw.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(
            f"Schema set multidisco non supportato: {raw.get('schema_version')!r}"
        )

    result: list[SavedDiscSet] = []
    used_paths: dict[Path, str] = {}
    for item in raw.get("sets", []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip() or "Set multidisco"
        set_id = str(item.get("id", "")).strip()
        entries: list[DiscEntry] = []
        numbers: set[int] = set()
        for disc in item.get("discs", []):
            if not isinstance(disc, dict):
                continue
            try:
                number = int(disc["number"])
                image = _validate_image(Path(str(disc["image"])), root)
            except (KeyError, TypeError, ValueError, RuntimeError) as exc:
                raise RuntimeError(f"Set '{name}' non valido: {exc}") from exc
            if number <= 0 or number in numbers:
                raise RuntimeError(f"Set '{name}': numero disco duplicato/non valido: {number}")
            other = used_paths.get(image)
            if other is not None and other != name:
                raise RuntimeError(
                    f"La stessa immagine è referenziata da due set ('{other}' e '{name}'): {image}"
                )
            used_paths[image] = name
            numbers.add(number)
            entries.append(
                DiscEntry(number, image, f"Disco {number} · {image.relative_to(root.resolve(strict=False))}")
            )
        entries.sort(key=lambda d: d.number)
        if not entries:
            continue
        discs = tuple(entries)
        if not set_id:
            set_id = _set_id_for(name, discs)
        result.append(SavedDiscSet(set_id, name, discs))
    return result


def save_saved_sets(sets: list[SavedDiscSet], root: Path) -> Path:
    # Revalidate every reference immediately before writing.  Saving metadata
    # must never create/rename/touch anything below the dump tree itself.
    normalized: list[SavedDiscSet] = []
    all_paths: set[Path] = set()
    for saved in sets:
        paths = [d.image for d in saved.discs]
        rebuilt = make_saved_set(saved.name, paths, root)
        # Preserve the stable id of an existing set across edits when possible.
        rebuilt = SavedDiscSet(saved.set_id or rebuilt.set_id, rebuilt.name, rebuilt.discs)
        for disc in rebuilt.discs:
            if disc.image in all_paths:
                raise RuntimeError(f"Immagine presente in più set: {disc.image}")
            all_paths.add(disc.image)
        normalized.append(rebuilt)

    lines = [f"schema_version = {SCHEMA_VERSION}", ""]
    for saved in normalized:
        lines += [
            "[[sets]]",
            f"id = {json.dumps(saved.set_id, ensure_ascii=False)}",
            f"name = {json.dumps(saved.name, ensure_ascii=False)}",
        ]
        for disc in saved.discs:
            lines += [
                "[[sets.discs]]",
                f"number = {disc.number}",
                f"image = {json.dumps(str(disc.image), ensure_ascii=False)}",
            ]
        lines.append("")

    path = disc_sets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def find_saved_set(selected: Path, sets: list[SavedDiscSet]) -> SavedDiscSet | None:
    selected = selected.resolve(strict=False)
    for saved in sets:
        if any(d.image.resolve(strict=False) == selected for d in saved.discs):
            return saved
    return None


def resolve_disc_set(
    selected: Path,
    all_images: list[Path],
    root: Path,
    sets: list[SavedDiscSet],
) -> DiscSet:
    """Resolve a disc set with explicit metadata taking absolute priority.

    Archive naming is deliberately irrelevant once a path has been associated
    with a saved set.  This is important for Redump/TOSEC variants such as
    ``(Alt)``, ``(Rerelease)`` or per-disc directory names that do not normalize
    to the same automatic grouping key.
    """
    saved = find_saved_set(selected, sets)
    if saved is not None:
        return saved.to_disc_set()
    return discover_disc_set(selected, all_images, root)


def upsert_saved_set(sets: list[SavedDiscSet], saved: SavedDiscSet) -> list[SavedDiscSet]:
    result = [s for s in sets if s.set_id != saved.set_id]
    # If one of the images was already associated with an older set, replacing
    # that association is less surprising than leaving an ambiguous mapping.
    paths = {d.image.resolve(strict=False) for d in saved.discs}
    result = [
        s for s in result
        if not any(d.image.resolve(strict=False) in paths for d in s.discs)
    ]
    result.append(saved)
    result.sort(key=lambda s: (s.name.casefold(), s.set_id))
    return result
