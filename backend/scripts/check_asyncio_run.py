#!/usr/bin/env python3
"""
Regression check: no ``asyncio.run`` may live under ``backend/routers/``.

This enforces Phase 2 of ``doc/refactoring/CURSOR_ASYNC_PLAN.md`` — FastAPI
``async def`` routes must never start a fresh event loop with ``asyncio.run``.
Stack frames that include a running event loop will raise ``RuntimeError`` on
Python 3.10+ once a nested ``asyncio.run`` is hit.

The check is intentionally minimal so it can run in CI without extra deps. It
exits with status ``1`` on any match.

Usage::

    python backend/scripts/check_asyncio_run.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERN = re.compile(r"\basyncio\.run\(")


# Path containing FastAPI route modules. Resolved relative to repo root so the
# script works from any cwd that contains the ``backend`` directory.
def _routers_dir() -> Path:
    here = Path(__file__).resolve()
    return here.parent.parent / "routers"


def main() -> int:
    routers = _routers_dir()
    if not routers.is_dir():
        print(f"routers directory not found at {routers}", file=sys.stderr)
        return 2

    hits: list[tuple[Path, int, str]] = []
    for py in routers.rglob("*.py"):
        try:
            text = py.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if PATTERN.search(line):
                hits.append((py, lineno, line.strip()))

    if not hits:
        print("[OK] no asyncio.run() in backend/routers/")
        return 0

    print("[FAIL] asyncio.run() found in router code:")
    for path, lineno, line in hits:
        print(f"  {path}:{lineno}: {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
