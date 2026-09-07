from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from disc_sets_backend import (
    SavedDiscSet,
    find_saved_set,
    resolve_disc_set,
    load_saved_sets,
    make_new_saved_set,
    make_saved_set,
    save_saved_sets,
    suggest_set_name,
)


class DiscSetsBackendTests(unittest.TestCase):
    def _redump_disc(self, root: Path, n: int) -> Path:
        folder = root / f"Discworld Noir (Europe) (En,Es,It) (Disc {n}) (Rerelease)"
        folder.mkdir(parents=True)
        cue = folder / f"Discworld Noir (Europe) (En,Es,It) (Disc {n}) (Rerelease).cue"
        binf = cue.with_suffix(".bin")
        cue.write_text(f'FILE "{binf.name}" BINARY\n', encoding="ascii")
        binf.write_bytes((f"ORIGINAL-DISC-{n}").encode("ascii"))
        return cue


    def test_new_explicit_set_starts_from_selected_disc_one_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p1 = root / "release-disc1" / "Game (Disc 1) (Rerelease).cue"
            p2 = root / "release-disc2-alt" / "Game (Disc 2) (Alt).cue"
            for p in (p1, p2):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('FILE "track.bin" BINARY\n', encoding="ascii")
            saved = make_new_saved_set(p1, root)
            self.assertEqual([1], [d.number for d in saved.discs])
            self.assertEqual([p1.resolve()], [d.image for d in saved.discs])
            self.assertNotIn(p2.resolve(), [d.image for d in saved.discs])

    def test_saved_set_preserves_original_redump_paths_and_files(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as cfg:
            root = Path(td)
            cues = [self._redump_disc(root, n) for n in (1, 2, 3)]
            before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in cues + [p.with_suffix('.bin') for p in cues]}
            with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": cfg}, clear=False):
                saved = make_saved_set("Discworld Noir", cues, root)
                path = save_saved_sets([saved], root)
                loaded = load_saved_sets(root)
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))
            self.assertEqual(0o700, stat.S_IMODE(path.parent.stat().st_mode))
            self.assertEqual([1, 2, 3], [d.number for d in loaded[0].discs])
            self.assertEqual(cues, [d.image for d in loaded[0].discs])
            for p, state in before.items():
                self.assertEqual(state, (p.read_bytes(), p.stat().st_mtime_ns))

    def test_explicit_set_can_join_unrelated_folder_names(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p1 = root / "archive-A" / "Game CD1.cue"
            p2 = root / "completely different folder" / "Game CD2.cue"
            p1.parent.mkdir(); p2.parent.mkdir()
            p1.touch(); p2.touch()
            saved = make_saved_set("Game", [p1, p2], root)
            self.assertEqual([1, 2], [d.number for d in saved.discs])
            self.assertEqual(saved, find_saved_set(p2, [saved]))

    def test_explicit_set_wins_for_alt_disc_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p1 = root / "Discworld Noir (Europe) (Disc 1) (Rerelease)" / "Discworld Noir (Europe) (Disc 1) (Rerelease).cue"
            p2 = root / "Discworld Noir (Europe) (Disc 2) (Alt)" / "Discworld Noir (Europe) (Disc 2) (Alt).cue"
            p3 = root / "Discworld Noir (Europe) (Disc 3)" / "Discworld Noir (Europe) (Disc 3).cue"
            for p in (p1, p2, p3):
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('FILE "track.bin" BINARY\n', encoding="utf-8")
            saved = make_saved_set("Discworld Noir", [p1, p2, p3], root)
            resolved = resolve_disc_set(p2, [p1, p2, p3], root, [saved])
            self.assertTrue(resolved.explicit)
            self.assertEqual([1, 2, 3], [d.number for d in resolved.discs])
            self.assertEqual(p2.resolve(), resolved.discs[1].image)

    def test_reference_outside_retropc_is_rejected(self):
        with tempfile.TemporaryDirectory() as td, tempfile.TemporaryDirectory() as outside:
            root = Path(td)
            image = Path(outside) / "Disc 1.cue"
            image.touch()
            with self.assertRaises(RuntimeError):
                make_saved_set("bad", [image], root)

    def test_suggest_name_removes_only_disc_ordinal(self):
        image = Path("Discworld Noir (Europe) (En,Es,It) (Disc 2) (Rerelease).cue")
        name = suggest_set_name(image)
        self.assertNotIn("Disc 2", name)
        self.assertIn("Discworld Noir", name)
        self.assertIn("Rerelease", name)


if __name__ == "__main__":
    unittest.main()
