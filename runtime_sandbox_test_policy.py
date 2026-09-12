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


def _blocked_dconf_rc(detail: str) -> bool:
    """Return True only for explicit non-zero dconf probe evidence.

    The legacy self-test records a completed probe as ``rc=<integer>``. Missing
    output (for example ``risultato assente``), malformed evidence and rc=127
    must never be promoted to PASS merely because the legacy layer labelled the
    result FAIL. rc=127 is reserved for missing probe tooling and is therefore
    not positive evidence that the proxy blocked host dconf.
    """
    if not detail.startswith("rc="):
        return False
    try:
        rc = int(detail[3:], 10)
    except ValueError:
        return False
    return rc not in (0, 127)


def normalize_sandbox_test_results(results: Iterable[TestResult]) -> list[TestResult]:
    """Return sandbox-test results with the dconf expectation inverted.

    A legacy PASS means dconf was reachable and is therefore a 0.4.1 failure.
    A legacy FAIL is promoted to PASS only when it carries explicit non-zero
    return-code evidence from the dconf probe. Missing/malformed evidence stays
    FAIL, while WARN (for example missing gdbus) remains WARN.
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
        elif state == "FAIL" and _blocked_dconf_rc(detail):
            normalized.append((
                "PASS",
                name,
                "host dconf bloccato; preferenze Bottles persistono via GSETTINGS_BACKEND=keyfile",
            ))
        else:
            # Missing/malformed evidence and WARN are deliberately preserved.
            # Security evidence must never be synthesized from an ambiguous
            # legacy failure state.
            normalized.append(raw)

    return normalized


__all__ = ["TestResult", "normalize_sandbox_test_results"]
