#!/usr/bin/env python3
"""
Regression check: no router module may import ``repositories``.

Enforces Router → Service → Repository (see ``doc/refactoring/CURSOR_REFACTOR_1.md``).

Usage::

    python backend/scripts/check_router_repositories.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path


def _routers_dir() -> Path:
    here = Path(__file__).resolve()
    return here.parent.parent / "routers"


def _is_repositories_root(name: str) -> bool:
    root = name.split(".", 1)[0]
    return root == "repositories"


def main() -> int:
    backend_root = _routers_dir().parent
    routers = _routers_dir()
    if not routers.is_dir():
        print(f"routers directory not found at {routers}", file=sys.stderr)
        return 2

    hits: list[str] = []
    for py in routers.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            print(f"[WARN] skip {py}: {exc}", file=sys.stderr)
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if _is_repositories_root(node.module):
                    rel = py.relative_to(backend_root)
                    hits.append(f"{rel}: from {node.module} import ...")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name and _is_repositories_root(alias.name):
                        rel = py.relative_to(backend_root)
                        hits.append(f"{rel}: import {alias.name}")

    if not hits:
        print("[OK] no repositories imports in backend/routers/")
        return 0

    print("[FAIL] Router modules must not import repositories:")
    for line in hits:
        print(f"  {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
