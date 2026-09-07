#!/usr/bin/env python3
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_DISC_RE = re.compile(r"(?i)(?<![a-z0-9])(?:disc|disk|cd)[\s_.-]*([0-9]{1,2})(?![0-9])")
_EXT_PREFERENCE = {
    ".cue": 0,
    ".mds": 1,
    ".ccd": 2,
    ".toc": 3,
    ".iso": 4,
    ".nrg": 5,
    ".mdx": 6,
    ".cdi": 7,
    ".bin": 20,
    ".img": 21,
}


@dataclass(frozen=True, slots=True)
class DiscEntry:
    number: int
    image: Path
    label: str


@dataclass(frozen=True, slots=True)
class DiscSet:
    key: str
    discs: tuple[DiscEntry, ...]
    name: str = ""
    explicit: bool = False

    @property
    def multidisc(self) -> bool:
        return len(self.discs) > 1


def disc_number(path: Path) -> int | None:
    """Extract a disc number, preferring the filename over parent folders."""
    parts = [path.stem, *reversed(path.parts[:-1])]
    for part in parts:
        match = _DISC_RE.search(part)
        if match:
            return int(match.group(1))
    return None


def _normalized_component(text: str) -> str:
    text = text.casefold()
    text = _DISC_RE.sub("disc#", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def disc_set_key(path: Path, root: Path) -> str | None:
    number = disc_number(path)
    if number is None:
        return None
    try:
        rel = path.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return None
    parts = list(rel.parts)
    if parts:
        parts[-1] = Path(parts[-1]).stem
    return "/".join(_normalized_component(part) for part in parts)


def _format_rank(path: Path) -> int:
    return _EXT_PREFERENCE.get(path.suffix.casefold(), 10)


def _canonical_candidates(images: list[Path]) -> list[Path]:
    """Prefer descriptor formats such as CUE over raw BIN duplicates."""
    resolved = [p.resolve(strict=False) for p in images]
    cue_stems = {(p.parent, p.stem.casefold()) for p in resolved if p.suffix.casefold() == ".cue"}
    result: list[Path] = []
    for path in resolved:
        if path.suffix.casefold() == ".bin" and (path.parent, path.stem.casefold()) in cue_stems:
            continue
        result.append(path)
    return result


def discover_disc_set(selected: Path, images: list[Path], root: Path) -> DiscSet:
    selected = selected.resolve(strict=False)
    selected_number = disc_number(selected)
    key = disc_set_key(selected, root)
    if selected_number is None or key is None:
        return DiscSet(str(selected), (DiscEntry(1, selected, f"Disco 1 · {selected.name}"),))

    per_number: dict[int, Path] = {}
    for image in _canonical_candidates(images):
        number = disc_number(image)
        if number is None or disc_set_key(image, root) != key:
            continue
        current = per_number.get(number)
        if current is None or (_format_rank(image), str(image).casefold()) < (
            _format_rank(current), str(current).casefold()
        ):
            per_number[number] = image

    # The selected image must remain available even if it is an uncommon format.
    current = per_number.get(selected_number)
    if current is None or _format_rank(selected) < _format_rank(current):
        per_number[selected_number] = selected

    discs = tuple(
        DiscEntry(number, image, f"Disco {number} · {image.name}")
        for number, image in sorted(per_number.items())
    )
    return DiscSet(key, discs or (DiscEntry(selected_number, selected, f"Disco {selected_number} · {selected.name}"),))
