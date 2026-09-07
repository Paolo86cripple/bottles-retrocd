from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import protection_scanner as ps


def dir_record(lba: int, size: int, flags: int, name: bytes) -> bytes:
    name_len = len(name)
    length = 33 + name_len + (0 if name_len % 2 else 1)
    rec = bytearray(length)
    rec[0] = length
    rec[2:6] = lba.to_bytes(4, 'little')
    rec[6:10] = lba.to_bytes(4, 'big')
    rec[10:14] = size.to_bytes(4, 'little')
    rec[14:18] = size.to_bytes(4, 'big')
    rec[25] = flags
    rec[28:30] = (1).to_bytes(2, 'little')
    rec[30:32] = (1).to_bytes(2, 'big')
    rec[32] = name_len
    rec[33:33+name_len] = name
    return bytes(rec)


def make_iso(path: Path, *, joliet: bool = False, raw: bool = False, filename: str = 'SAFE.EXE', content: bytes = b'SafeDisc') -> Path:
    sector_size = 2352 if raw else 2048
    offset = 16 if raw else 0
    sectors = [bytearray(sector_size) for _ in range(40)]

    def put_user(lba: int, data: bytes):
        sectors[lba][offset:offset+len(data)] = data

    pvd = bytearray(2048)
    pvd[0] = 1; pvd[1:6] = b'CD001'; pvd[6] = 1
    pvd[40:72] = b'TESTVOL'.ljust(32, b' ')
    pvd[156:190] = dir_record(20, 2048, 2, b'\x00')[:34]
    put_user(16, pvd)

    if joliet:
        svd = bytearray(2048)
        svd[0] = 2; svd[1:6] = b'CD001'; svd[6] = 1; svd[88:91] = b'%/E'
        vol = 'JOLIET'.encode('utf-16-be')
        svd[40:40+len(vol)] = vol
        svd[156:190] = dir_record(21, 2048, 2, b'\x00')[:34]
        put_user(17, svd)
        root_lba = 21
        name = filename.encode('utf-16-be')
    else:
        root_lba = 20
        name = filename.encode('ascii')

    term = bytearray(2048); term[0] = 255; term[1:6] = b'CD001'; term[6] = 1
    put_user(18 if joliet else 17, term)

    root = bytearray(2048)
    records = [dir_record(root_lba, 2048, 2, b'\x00'), dir_record(root_lba, 2048, 2, b'\x01'), dir_record(22, len(content), 0, name)]
    pos = 0
    for rec in records:
        root[pos:pos+len(rec)] = rec; pos += len(rec)
    put_user(root_lba, root)
    put_user(22, content)

    path.write_bytes(b''.join(sectors))
    return path


class ProtectionScannerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    # 36
    def test_raw_signature_safedisc(self):
        image = self.root / 'raw.bin'; image.write_bytes(b'xx SafeDisc yy')
        result = ps.scan_image(image)
        self.assertIn('SafeDisc', [x.protection for x in result.findings])

    # 37
    def test_raw_signature_securom_case_insensitive(self):
        image = self.root / 'raw.bin'; image.write_bytes(b'xx SECUROM yy')
        result = ps.scan_image(image)
        self.assertIn('SecuROM', [x.protection for x in result.findings])

    # 38
    def test_no_signature(self):
        image = self.root / 'raw.bin'; image.write_bytes(b'plain data')
        result = ps.scan_image(image)
        self.assertEqual(result.findings, ())

    # 39
    def test_iso2048_layout(self):
        image = make_iso(self.root / 'disc.iso')
        reader = ps.SectorReader(image)
        self.assertEqual((reader.sector_size, reader.data_offset), (2048, 0))

    # 40
    def test_raw2352_layout(self):
        image = make_iso(self.root / 'disc.bin', raw=True)
        reader = ps.SectorReader(image)
        self.assertEqual((reader.sector_size, reader.data_offset), (2352, 16))

    # 41
    def test_iso_filename_and_content_findings(self):
        image = make_iso(self.root / 'disc.iso', filename='SECDRV.SYS', content=b'SafeDisc secdrv.sys')
        result = ps.scan_image(image)
        finding = next(x for x in result.findings if x.protection == 'SafeDisc')
        self.assertIn(finding.confidence, {'alta', 'media'})
        self.assertGreater(result.files_seen, 0)

    # 42
    def test_joliet_volume_and_filename(self):
        image = make_iso(self.root / 'disc.iso', joliet=True, filename='CMS_NT.DLL', content=b'SecuROM')
        result = ps.scan_image(image)
        self.assertIn('Joliet', result.filesystem)
        self.assertEqual(result.volume_id, 'JOLIET')
        self.assertIn('SecuROM', [x.protection for x in result.findings])

    # 43
    def test_compare_catalog_consistent(self):
        image = self.root / 'raw.bin'; image.write_bytes(b'SafeDisc secdrv.sys')
        scan = ps.scan_image(image)
        lines = ps.compare_catalog_protection('SafeDisc 2.0', scan)
        self.assertIn('coerenti', lines[0])

    # 44
    def test_compare_catalog_declared_not_found(self):
        image = self.root / 'raw.bin'; image.write_bytes(b'plain')
        scan = ps.scan_image(image)
        lines = ps.compare_catalog_protection('SecuROM', scan)
        self.assertIn('non ha trovato', lines[0])

    # 45
    def test_compare_catalog_empty_but_observed(self):
        image = self.root / 'raw.bin'; image.write_bytes(b'StarForce sfdrv')
        scan = ps.scan_image(image)
        lines = ps.compare_catalog_protection('', scan)
        self.assertIn('scanner osserva', lines[0])

    # 46
    def test_format_scan(self):
        image = self.root / 'raw.bin'; image.write_bytes(b'LaserLock')
        text = ps.format_scan(ps.scan_image(image))
        self.assertIn('LaserLock', text)
        self.assertIn('nessun mount/esecuzione', text)


if __name__ == '__main__':
    unittest.main()
