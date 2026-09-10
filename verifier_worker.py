#!/usr/bin/env python3
"""Read-only verifier/scanner worker intended to run only inside verifier_sandbox."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from protection_scanner import compare_catalog_protection, format_scan, scan_image
from verifier_backend import CatalogIndex, descriptor_payloads, format_verification


_ALLOWED_OPERATIONS = frozenset({"verify", "verify-set", "scan", "verify-scan"})


def _canonical_root(raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise RuntimeError("Radice archivio worker non valida.")
    root = Path(raw).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise RuntimeError(f"Radice archivio worker non è una directory: {root}")
    return root


def _canonical_paths(raw: object, root: Path) -> tuple[Path, ...]:
    if not isinstance(raw, list) or not raw:
        raise RuntimeError("Lista input worker non valida o vuota.")
    result: list[Path] = []
    for item in raw:
        if not isinstance(item, str) or not item:
            raise RuntimeError("Input worker non valido.")
        path = Path(item).expanduser().resolve(strict=True)
        if not path.is_file():
            raise RuntimeError(f"Input worker non è un file: {path}")
        if not path.is_relative_to(root):
            raise RuntimeError(f"Input worker fuori dall'archivio autorizzato: {path}")
        result.append(path)
    return tuple(result)


def _scan_descriptor(descriptor: Path, root: Path) -> tuple[Path, ...] | tuple[()]:
    return descriptor_payloads(descriptor, root)


def _scan_text(descriptor: Path, root: Path) -> str:
    payloads = _scan_descriptor(descriptor, root)
    parts = [f"Scanner descriptor: {descriptor.name} · {len(payloads)} payload"]
    for payload in payloads:
        try:
            scan = scan_image(payload)
        except Exception as exc:
            parts.append(f"[WARN] {payload.name}: scanner non applicabile: {exc}")
            continue
        parts.append(format_scan(scan))
    return "\n\n".join(parts)


def _verify_scan_text(descriptor: Path, root: Path, index: CatalogIndex) -> tuple[str, str, bool]:
    verified = index.verify(descriptor, root)
    parts = [format_verification(verified)]
    declared = verified.exact_matches[0].protection if verified.matched else ""
    for payload in _scan_descriptor(descriptor, root):
        try:
            scan = scan_image(payload)
        except Exception as exc:
            parts.append(f"[WARN] {payload.name}: scanner non applicabile: {exc}")
            continue
        parts.append(format_scan(scan))
        parts.extend(f"[DAT↔SCANNER] {line}" for line in compare_catalog_protection(declared, scan))
    return "\n\n".join(parts), verified.status, verified.matched


def handle_request(request: object) -> dict[str, object]:
    if not isinstance(request, dict):
        raise RuntimeError("Richiesta worker non valida.")
    operation = request.get("operation")
    if not isinstance(operation, str) or operation not in _ALLOWED_OPERATIONS:
        raise RuntimeError(f"Operazione worker non consentita: {operation!r}")

    root = _canonical_root(request.get("root"))
    paths = _canonical_paths(request.get("paths"), root)
    index = CatalogIndex()

    if operation == "verify":
        if len(paths) != 1:
            raise RuntimeError("verify richiede esattamente un input.")
        result = index.verify(paths[0], root)
        return {
            "ok": True,
            "text": format_verification(result),
            "status": result.status,
            "matched": result.matched,
        }

    if operation == "verify-set":
        if len(paths) < 2:
            raise RuntimeError("verify-set richiede almeno due descriptor.")
        result = index.verify_set(paths, root)
        parts = [f"Set multidisco: {result.status} · {len(result.results)} supporti"]
        parts.extend(format_verification(item) for item in result.results)
        return {
            "ok": True,
            "text": "\n\n".join(parts),
            "status": result.status,
            "matched": result.status == "MATCH",
        }

    if operation == "scan":
        if len(paths) != 1:
            raise RuntimeError("scan richiede esattamente un input.")
        return {
            "ok": True,
            "text": _scan_text(paths[0], root),
            "status": "SCAN",
            "matched": None,
        }

    if operation == "verify-scan":
        if len(paths) != 1:
            raise RuntimeError("verify-scan richiede esattamente un input.")
        text, status, matched = _verify_scan_text(paths[0], root, index)
        return {"ok": True, "text": text, "status": status, "matched": matched}

    raise RuntimeError("Operazione worker non raggiungibile.")


def main() -> int:
    if os.environ.get("RETROCD_VERIFIER_SANDBOX") != "1":
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "worker rifiutato fuori dal boundary verifier sandbox",
                },
                ensure_ascii=False,
            )
        )
        return 70

    try:
        request = json.load(sys.stdin)
        response = handle_request(request)
    except Exception as exc:
        response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(response, ensure_ascii=False))
        return 2

    print(json.dumps(response, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
