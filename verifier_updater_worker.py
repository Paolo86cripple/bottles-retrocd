#!/usr/bin/env python3
"""Official Redump/TOSEC updater worker intended to run only in its bwrap boundary."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from verifier_updates import update_official_source


_ALLOWED_SOURCES = frozenset({"redump", "tosec"})


def handle_request(request: object) -> dict[str, object]:
    if not isinstance(request, dict):
        raise RuntimeError("Richiesta updater non valida.")

    source = request.get("source")
    if not isinstance(source, str) or source not in _ALLOWED_SOURCES:
        raise RuntimeError(f"Sorgente updater non consentita: {source!r}")

    forbidden_archive = request.get("forbidden_archive")
    if forbidden_archive is not None:
        if not isinstance(forbidden_archive, str) or not forbidden_archive:
            raise RuntimeError("Radice archivio vietata non valida.")
        # Positive proof: the updater must not be able to see the configured
        # game archive at all. Parent directories may exist synthetically.
        if Path(forbidden_archive).exists():
            raise RuntimeError("Archivio giochi visibile nel sandbox updater: aggiornamento rifiutato.")

    report = update_official_source(source)
    return {
        "ok": True,
        "source": report.source,
        "url": report.url,
        "dat_files": report.dat_files,
        "games": report.games,
        "roms": report.roms,
        "catalog_path": str(report.catalog_path),
    }


def main() -> int:
    if os.environ.get("RETROCD_UPDATER_SANDBOX") != "1":
        print(
            json.dumps(
                {"ok": False, "error": "updater rifiutato fuori dal boundary sandbox"},
                ensure_ascii=False,
            )
        )
        return 70

    try:
        request = json.load(sys.stdin)
        response = handle_request(request)
    except Exception as exc:
        print(
            json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False)
        )
        return 2

    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
