#!/usr/bin/env python3
"""Regression guard: no leaky 5xx detail strings under ``backend/routers/``.

Forbidden patterns inside an ``HTTPException(...)`` call whose status is a
server error (5xx): ``detail=str(...)``, ``detail=f"...{e}..."``, etc.

The check uses balanced-paren extraction (with string literal skipping) so
nested calls like ``detail=str(e)`` are attributed to the correct
``HTTPException`` block.

Trade-off: intentionally regex/heuristic-based (no AST) so it runs without
extra deps; false negatives are possible for unusual formatting.

Usage::

    python backend/scripts/check_http_500_leaks.py

Allow-list (``ALLOW_LIST``) must stay **empty**; entries are not permitted
for new regressions (see ``doc/refactoring/REFACTORE_SANITIZED_ERRORS.md``).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Relative to ``backend/`` — must remain empty once the sweep is complete.
ALLOW_LIST: set[str] = set()

_STATUS_5XX = re.compile(
    r"(?:status\s*\.\s*)?HTTP_5\d\d(?:_[A-Z_]+)?\b|status_code\s*=\s*5\d\d\b"
)

_LEAK_PATTERNS = (
    re.compile(r"detail\s*=\s*str\s*\(", re.I),
    re.compile(r"detail\s*=\s*error_msg\b"),
    re.compile(r"detail\s*=\s*f[\"'][^\"']*\{(?:e|exc|error)\}[^\"']*[\"']"),
    re.compile(
        r"detail\s*=\s*f[\"'][^\"']*\{str\s*\(\s*(?:e|exc|error)\s*\)\}[^\"']*[\"']"
    ),
    # Catch dict lookups forwarding external/agent error strings into 5xx detail
    re.compile(r"detail\s*=\s*\w+\.get\s*\("),
    re.compile(r'detail\s*=\s*\w+\s*\[\s*["\']'),
)


def _extract_balanced_paren(source: str, open_paren_idx: int) -> str | None:
    """``source[open_paren_idx]`` must be ``'('``. Returns the span ``(...)`` including both parens."""
    depth = 0
    i = open_paren_idx
    n = len(source)
    while i < n:
        ch = source[i]
        if ch in ("'", '"'):
            quote = ch
            i += 1
            while i < n:
                if source[i] == "\\":
                    i += 2
                    continue
                if source[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if ch == "#":
            while i < n and source[i] != "\n":
                i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return source[open_paren_idx : i + 1]
        i += 1
    return None


def _iter_http_exception_blocks(text: str) -> list[tuple[int, str]]:
    """Return ``(line_no, block)`` for each ``HTTPException(...)`` call."""
    hits: list[tuple[int, str]] = []
    pos = 0
    token = "HTTPException"
    while True:
        idx = text.find(token, pos)
        if idx == -1:
            break
        j = idx + len(token)
        while j < len(text) and text[j].isspace():
            j += 1
        if j >= len(text) or text[j] != "(":
            pos = idx + 1
            continue
        arg_span = _extract_balanced_paren(text, j)
        if arg_span is None:
            pos = idx + 1
            continue
        block = token + arg_span
        line_no = text[:idx].count("\n") + 1
        hits.append((line_no, block))
        pos = j + len(arg_span)
    return hits


def _routers_dir() -> Path:
    here = Path(__file__).resolve()
    return here.parent.parent / "routers"


def _scan_file(path: Path) -> list[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    failures: list[tuple[int, str]] = []
    for line_no, block in _iter_http_exception_blocks(text):
        if not _STATUS_5XX.search(block):
            continue
        if any(p.search(block) for p in _LEAK_PATTERNS):
            snippet = block.split("\n", 1)[0].strip()
            if len(snippet) > 160:
                snippet = snippet[:157] + "..."
            failures.append((line_no, snippet))
    return failures


def main() -> int:
    routers = _routers_dir()
    if not routers.is_dir():
        print(f"routers directory not found at {routers}", file=sys.stderr)
        return 2

    backend_dir = routers.parent
    all_failures: list[tuple[Path, int, str]] = []
    for py in sorted(routers.rglob("*.py")):
        rel = py.relative_to(backend_dir).as_posix()
        if rel in ALLOW_LIST:
            continue
        for line_no, snippet in _scan_file(py):
            all_failures.append((py, line_no, snippet))

    if not all_failures:
        print("[OK] no leaky 5xx HTTPException detail strings under backend/routers/")
        return 0

    print("[FAIL] leaky 5xx HTTPException detail in:")
    for path, line_no, snippet in all_failures:
        print(f"  {path}:{line_no}: {snippet}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
