#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from protection_scanner import compare_catalog_protection, format_scan, scan_image
from verifier_backend import (
    CatalogIndex,
    descriptor_payloads,
    format_verification,
    import_dat_directory,
    update_official_source,
)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bottles Retro CD Redump/TOSEC verifier")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("stats", help="show catalog statistics")

    verify = sub.add_parser("verify", help="verify one descriptor/image")
    verify.add_argument("path", type=Path)
    verify.add_argument("--root", type=Path)

    verify_set = sub.add_parser("verify-set", help="verify multiple disc descriptors")
    verify_set.add_argument("paths", nargs="+", type=Path)
    verify_set.add_argument("--root", type=Path)

    scan = sub.add_parser("scan", help="scan image payloads for protection signatures")
    scan.add_argument("path", type=Path)
    scan.add_argument("--root", type=Path)

    compare = sub.add_parser("verify-scan", help="verify and explicitly compare DAT protection metadata with scanner")
    compare.add_argument("path", type=Path)
    compare.add_argument("--root", type=Path)

    update = sub.add_parser("update", help="update an official DAT source")
    update.add_argument("source", choices=("redump", "tosec"))

    imp = sub.add_parser("import", help="import local DAT/XML files under a separate source name")
    imp.add_argument("source")
    imp.add_argument("directory", type=Path)
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    index = CatalogIndex()
    if args.command == "stats":
        stats = index.stats()
        print(f"catalogs={stats['catalogs']} games={stats['games']} roms={stats['roms']}")
        return 0
    if args.command == "verify":
        result = index.verify(args.path, args.root)
        print(format_verification(result))
        return 0 if result.matched else 2
    if args.command == "verify-set":
        result = index.verify_set(args.paths, args.root)
        print(f"SET {result.status}")
        for item in result.results:
            print(format_verification(item))
            print()
        return 0 if result.status == "MATCH" else 2
    if args.command == "scan":
        root = args.root or args.path.resolve(strict=True).parent
        for payload in descriptor_payloads(args.path, root):
            print(format_scan(scan_image(payload)))
            print()
        return 0
    if args.command == "verify-scan":
        root = args.root or args.path.resolve(strict=True).parent
        result = index.verify(args.path, root)
        print(format_verification(result))
        declared = result.exact_matches[0].protection if result.matched else ""
        for payload in descriptor_payloads(args.path, root):
            scan = scan_image(payload)
            print()
            print(format_scan(scan))
            for line in compare_catalog_protection(declared, scan):
                print(f"DAT↔SCANNER: {line}")
        return 0 if result.matched else 2
    if args.command == "update":
        report = update_official_source(args.source, catalog=index)
        print(
            f"{report.source}: dat={report.dat_files} games={report.games} "
            f"roms={report.roms} index={report.catalog_path}"
        )
        return 0
    if args.command == "import":
        report = import_dat_directory(args.source, args.directory, catalog=index)
        print(
            f"{report.source}: dat={report.dat_files} games={report.games} "
            f"roms={report.roms} index={report.catalog_path}"
        )
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
