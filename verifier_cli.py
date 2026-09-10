#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from verifier_backend import CatalogIndex, import_dat_directory, update_official_source
from verifier_sandbox import VerifierSandbox


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Bottles Retro CD Redump/TOSEC verifier")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("stats", help="show catalog statistics")

    verify = sub.add_parser("verify", help="verify one descriptor/image in the dedicated sandbox")
    verify.add_argument("path", type=Path)
    verify.add_argument("--root", type=Path)

    verify_set = sub.add_parser("verify-set", help="verify multiple disc descriptors in the dedicated sandbox")
    verify_set.add_argument("paths", nargs="+", type=Path)
    verify_set.add_argument("--root", type=Path)

    scan = sub.add_parser("scan", help="scan image payloads for protection signatures in the dedicated sandbox")
    scan.add_argument("path", type=Path)
    scan.add_argument("--root", type=Path)

    compare = sub.add_parser("verify-scan", help="verify and compare DAT metadata with scanner in the dedicated sandbox")
    compare.add_argument("path", type=Path)
    compare.add_argument("--root", type=Path)

    update = sub.add_parser("update", help="update an official DAT source")
    update.add_argument("source", choices=("redump", "tosec"))

    imp = sub.add_parser("import", help="import local DAT/XML files under a separate source name")
    imp.add_argument("source")
    imp.add_argument("directory", type=Path)
    return p


def _root_for(path: Path, root: Path | None) -> Path:
    return root or path.expanduser().resolve(strict=True).parent


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    index = CatalogIndex()
    sandbox = VerifierSandbox()

    if args.command == "stats":
        stats = index.stats()
        print(f"catalogs={stats['catalogs']} games={stats['games']} roms={stats['roms']}")
        return 0
    if args.command == "verify":
        result = sandbox.verify(args.path, _root_for(args.path, args.root))
        print(result.text)
        return 0 if result.matched else 2
    if args.command == "verify-set":
        if not args.paths:
            return 2
        root = args.root or args.paths[0].expanduser().resolve(strict=True).parent
        result = sandbox.verify_set(args.paths, root)
        print(result.text)
        return 0 if result.matched else 2
    if args.command == "scan":
        result = sandbox.scan(args.path, _root_for(args.path, args.root))
        print(result.text)
        return 0
    if args.command == "verify-scan":
        result = sandbox.verify_scan(args.path, _root_for(args.path, args.root))
        print(result.text)
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
