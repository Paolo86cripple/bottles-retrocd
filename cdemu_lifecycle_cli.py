#!/usr/bin/env python3
from __future__ import annotations

from cdemu_lifecycle import format_report, inspect_lifecycle


def main() -> int:
    report = inspect_lifecycle()
    print(format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
