from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from multidisc_backend import disc_number, discover_disc_set


class MultidiscBackendTests(unittest.TestCase):
    def test_disc_number_from_discworld_style_path(self):
        p = Path("Discworld Noir (Europe) (Disc 3) (Rerelease)/Discworld Noir (Europe) (Disc 3) (Rerelease).cue")
        self.assertEqual(3, disc_number(p))

    def test_disc_set_groups_sibling_disc_directories_and_prefers_cue(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            images = []
            for n in (1, 2, 3):
                d = root / f"Discworld Noir (Europe) (En,Es,It) (Disc {n}) (Rerelease)"
                d.mkdir()
                cue = d / f"Discworld Noir (Europe) (En,Es,It) (Disc {n}) (Rerelease).cue"
                raw = cue.with_suffix(".bin")
                cue.touch(); raw.touch()
                images += [raw, cue]
            ds = discover_disc_set(images[1], images, root)
            self.assertTrue(ds.multidisc)
            self.assertEqual([1, 2, 3], [x.number for x in ds.discs])
            self.assertTrue(all(x.image.suffix == ".cue" for x in ds.discs))

    def test_single_disc_falls_back_safely(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            image = root / "game.iso"
            image.touch()
            ds = discover_disc_set(image, [image], root)
            self.assertFalse(ds.multidisc)
            self.assertEqual(image, ds.discs[0].image)


if __name__ == "__main__":
    unittest.main()
