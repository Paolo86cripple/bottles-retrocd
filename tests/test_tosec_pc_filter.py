from __future__ import annotations

import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path

from verifier_updates import TOSEC_PC_PREFIX, UpdateError, _materialise_dat_payload


def dat_xml(name: str) -> bytes:
    return (
        '<?xml version="1.0"?><datafile><header><name>Test</name></header>'
        f'<game name="{name}"><rom name="x.bin" size="1" crc="8cdc1683" /></game>'
        '</datafile>'
    ).encode()


def archive(entries: dict[str, bytes]) -> bytes:
    out = BytesIO()
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, payload in entries.items():
            zf.writestr(name, payload)
    return out.getvalue()


class TosecPcFilterTests(unittest.TestCase):
    def test_tosec_extracts_only_ibm_pc_compatibles(self):
        payload = archive(
            {
                f"TOSEC/{TOSEC_PC_PREFIX} Games - [IMG] (TOSEC-v1).dat": dat_xml("PC floppy"),
                f"TOSEC-ISO/{TOSEC_PC_PREFIX} CD - Games - [BIN] (TOSEC-v1).dat": dat_xml("PC CD"),
                "TOSEC/Commodore Amiga - Games (TOSEC-v1).dat": dat_xml("Amiga"),
            }
        )
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "tosec"
            count = _materialise_dat_payload(payload, dest, "tosec")
            names = sorted(path.name for path in dest.iterdir())
        self.assertEqual(count, 2)
        self.assertEqual(len(names), 2)
        self.assertTrue(all(name.startswith(TOSEC_PC_PREFIX) for name in names))

    def test_tosec_without_pc_dat_fails_closed(self):
        payload = archive({"TOSEC/Commodore Amiga - Games.dat": dat_xml("Amiga")})
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(UpdateError):
                _materialise_dat_payload(payload, Path(td) / "tosec", "tosec")

    def test_other_zip_sources_are_not_filtered(self):
        payload = archive(
            {
                "redump-a.dat": dat_xml("A"),
                "redump-b.dat": dat_xml("B"),
            }
        )
        with tempfile.TemporaryDirectory() as td:
            dest = Path(td) / "redump"
            count = _materialise_dat_payload(payload, dest, "redump")
            names = sorted(path.name for path in dest.iterdir())
        self.assertEqual(count, 2)
        self.assertEqual(names, ["redump-a.dat", "redump-b.dat"])


if __name__ == "__main__":
    unittest.main()
