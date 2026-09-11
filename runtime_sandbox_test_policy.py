#!/usr/bin/env python3
"""Policy normalization for the 0.4.1 Bubblejail self-test.

The released 0.4.0 self-test treated successful access to host dconf as a
positive capability check. 0.4.1 deliberately uses GSETTINGS_BACKEND=keyfile
inside Bubblejail and requires host dconf to remain blocked, so that legacy
result must be inverted without weakening any other sandbox-test semantics.
"""
from __future__ import annotations

from collections.abc import Iterable

TestResult = tuple[str, str, str]
_DCONF_LABEL = "dconf D-Bus"
_VALID_STATES = frozenset({"PASS", "FAIL", "WARN"})


def normalize_sandbox_test_results(results: Iterable[TestResult]) -> list[TestResult]:
    """Return sandbox-test results with the dconf expectation inverted.

    A legacy PASS means dconf was reachable and is therefore a 0.4.1 failure.
    A legacy FAIL means the dconf call was blocked/unavailable and is the
    desired result. WARN (for example missing gdbus) remains WARN so missing
    evidence is never promoted to PASS.
    """
    normalized: list[TestResult] = []
    dconf_seen = False

    for raw in results:
        if not isinstance(raw, tuple) or len(raw) != 3:
            raise RuntimeError("Risultato test Bubblejail non valido.")
        state, name, detail = raw
        if state not in _VALID_STATES or not all(isinstance(item, str) for item in raw):
            raise RuntimeError("Risultato test Bubblejail non valido.")

        if name != _DCONF_LABEL:
            normalized.append(raw)
            continue

        if dconf_seen:
            raise RuntimeError("Risultato dconf D-Bus duplicato nel test Bubblejail.")
        dconf_seen = True

        if state == "PASS":
            normalized.append((
                "FAIL",
                name,
                "host dconf raggiungibile; 0.4.1 richiede dconf bloccato con GSETTINGS_BACKEND=keyfile",
            ))
        elif state == "FAIL":
            normalized.append((
                "PASS",
                name,
                "host dconf bloccato; preferenze Bottles persistono via GSETTINGS_BACKEND=keyfile",
            ))
        else:
            normalized.append(raw)

    return normalized


__all__ = ["TestResult", "normalize_sandbox_test_results"]
