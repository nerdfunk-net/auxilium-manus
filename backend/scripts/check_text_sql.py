#!/usr/bin/env python3
"""Regression guard: no runtime ``sqlalchemy.text()`` outside the allow-list.

Allow-listed locations are documented in ``doc/refactoring/REFACTORING_RAW_SQL.md`` §3.
Run alongside ``check_asyncio_run.py`` and ``check_http_500_leaks.py``::

    cd backend && python scripts/check_text_sql.py

Exit code ``1`` if any forbidden ``text(`` call is found.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PATTERN = re.compile(r"\btext\s*\(")

ALLOWED_PREFIXES = (
    "migrations/",
    "tests/",
    "tools/",
    "scripts/",
    "static/",
)
ALLOWED_FILES = frozenset(
    {
        "core/database.py",
        "core/schema_manager.py",
    }
)
# SQLAlchemy Index/Constraint dialect kwargs (not runtime query SQL).
_INDEX_PREDICATE = re.compile(r"postgresql_where\s*=\s*text\s*\(")


def _backend_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _forbidden_line(line: str) -> bool:
    s = line.strip()
    if s.startswith("#"):
        return False
    if ".read_text(" in line or ".write_text(" in line:
        return False
    if "sqlalchemy.text" in line:
        return False
    # Partial-index predicates on models are schema DDL, not repository SQL.
    if _INDEX_PREDICATE.search(line):
        return False
    return bool(PATTERN.search(line))


def main() -> int:
    root = _backend_root()
    failures: list[tuple[Path, int, str]] = []

    for py in root.rglob("*.py"):
        rel = py.relative_to(root).as_posix()
        if rel.startswith(ALLOWED_PREFIXES) or rel in ALLOWED_FILES:
            continue
        try:
            src = py.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if "from sqlalchemy" not in src and "import sqlalchemy" not in src:
            continue
        for lineno, line in enumerate(src.splitlines(), start=1):
            if _forbidden_line(line):
                failures.append((py, lineno, line.strip()))

    if not failures:
        print("[OK] no forbidden sqlalchemy.text() outside allow-list")
        return 0

    print("[FAIL] sqlalchemy.text() outside allow-list:", file=sys.stderr)
    for path, lineno, line in failures:
        rel = path.relative_to(root)
        print(f"  {rel}:{lineno}: {line}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
