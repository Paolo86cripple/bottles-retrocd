#!/usr/bin/env python3
"""Public facade for the Bottles RetroCD Redump/TOSEC verifier.

Implementation is split into focused modules so descriptor parsing, hashing,
catalog indexing and transactional DAT updates can be reviewed independently.
"""
from __future__ import annotations

# Re-export os deliberately: the regression suite fault-injects os.replace to
# verify rollback behavior across the updater modules.
import os

from verifier_common import (
    APP_DIRNAME, CATALOG_SCHEMA, HASH_CACHE_SCHEMA, HASH_CHUNK_SIZE,
    MAX_ARCHIVE_MEMBERS, MAX_DOWNLOAD_BYTES, MAX_MEMBER_BYTES,
    MAX_TOTAL_UNPACKED_BYTES, OFFICIAL_UPDATE_HOSTS, REDUMP_PC_URL,
    TOSEC_DOWNLOADS_URL, TOSEC_FALLBACK_URL, CatalogMatch, FileHash, FileMatch,
    SetVerificationResult, UpdateError, UpdateReport, VerificationError,
    VerificationResult, _safe_catalog_source, descriptor_payloads,
    parse_cue_payloads, parse_toc_payloads, verifier_cache_dir, verifier_data_dir,
)
from verifier_hash import HashCache, hash_file
from verifier_catalog import CatalogIndex
from verifier_updates import (
    _materialise_dat_payload, _safe_zip_members, _validate_update_url,
    import_dat_directory, resolve_latest_tosec_url, update_official_source,
)

def format_verification(result: VerificationResult) -> str:
    lines = [f"[{result.status}] {result.descriptor.name}", result.detail]
    for payload in result.payloads:
        cache = "cache" if payload.cached else "calcolato"
        lines.append(
            f"  {payload.path.name}: size={payload.size} crc32={payload.crc32} "
            f"md5={payload.md5} sha1={payload.sha1} ({cache})"
        )
    for match in result.exact_matches:
        extras = []
        if match.serial:
            extras.append(f"serial={match.serial}")
        if match.version:
            extras.append(f"version={match.version}")
        if match.protection:
            extras.append(f"protection={match.protection}")
        suffix = " · " + " · ".join(extras) if extras else ""
        lines.append(
            f"  => {match.source.upper()} · {match.description or match.game_name} · {match.catalog}{suffix}"
        )
    if not result.exact_matches:
        for item in result.file_matches:
            lines.append(f"  {item.file.path.name}: {len(item.candidates)} candidati individuali")
    return "\n".join(lines)
