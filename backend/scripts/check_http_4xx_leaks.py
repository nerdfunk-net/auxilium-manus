#!/usr/bin/env python3
"""Regression guard: a 4xx ``detail`` must not echo a caught built-in exception verbatim.

Inside an ``except`` handler for a built-in exception (``ValueError``, ``OSError`` and its
subclasses, ``KeyError``, ``Exception``, ...), an ``HTTPException`` whose ``detail`` is
``str(exc)`` or an f-string containing ``{exc}`` is forbidden: pydantic's ``ValidationError`` is a
``ValueError`` and an OS error carries a server path, so the text can leak library internals.
Use ``core.safe_http_errors.client_error_message(exc)`` instead.

Handlers for the project's own exception types (``DomainError`` subclasses, ``*ValidationError``
and friends) are not checked: their messages are written for the user.

Usage::

    python backend/scripts/check_http_4xx_leaks.py

The 5xx counterpart is ``check_http_500_leaks.py``. ``ALLOW_LIST`` must stay empty.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ALLOW_LIST: set[str] = set()

BUILTIN_EXCEPTIONS = frozenset(
    {
        "Exception",
        "BaseException",
        "ValueError",
        "TypeError",
        "KeyError",
        "IndexError",
        "AttributeError",
        "RuntimeError",
        "OSError",
        "IOError",
        "FileNotFoundError",
        "FileExistsError",
        "PermissionError",
        "IsADirectoryError",
        "NotADirectoryError",
        "UnicodeError",
        "UnicodeDecodeError",
        "UnicodeEncodeError",
        "ValidationError",
    }
)


def _handler_names(handler: ast.ExceptHandler) -> set[str]:
    node = handler.type
    if node is None:
        return {"BaseException"}
    nodes = node.elts if isinstance(node, ast.Tuple) else [node]
    names: set[str] = set()
    for item in nodes:
        if isinstance(item, ast.Name):
            names.add(item.id)
        elif isinstance(item, ast.Attribute):
            names.add(item.attr)
    return names


def _echoes(detail: ast.expr, name: str) -> bool:
    """True when ``detail`` is, or contains, ``str(name)``, ``name`` or an f-string using it."""
    if isinstance(detail, ast.Name):
        return detail.id == name
    if (
        isinstance(detail, ast.Call)
        and isinstance(detail.func, ast.Name)
        and detail.func.id == "str"
    ):
        return any(isinstance(a, ast.Name) and a.id == name for a in detail.args)
    if isinstance(detail, ast.JoinedStr):
        return any(
            isinstance(part, ast.FormattedValue) and _echoes(part.value, name)
            for part in detail.values
        )
    if isinstance(detail, ast.Dict):
        return any(value is not None and _echoes(value, name) for value in detail.values)
    if isinstance(detail, (ast.List, ast.Tuple)):
        return any(_echoes(item, name) for item in detail.elts)
    return False


def _detail_expressions(call: ast.Call) -> list[ast.expr]:
    """The ``detail`` argument of an ``HTTPException(status_code, detail)`` call."""
    found = [kw.value for kw in call.keywords if kw.arg == "detail"]
    if len(call.args) >= 2:
        found.append(call.args[1])
    return found


def _is_http_exception(call: ast.Call) -> bool:
    func = call.func
    return (isinstance(func, ast.Name) and func.id == "HTTPException") or (
        isinstance(func, ast.Attribute) and func.attr == "HTTPException"
    )


def scan_source(source: str) -> list[tuple[int, str]]:
    failures: list[tuple[int, str]] = []
    for handler in (n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ExceptHandler)):
        if not handler.name or not (_handler_names(handler) & BUILTIN_EXCEPTIONS):
            continue
        for node in ast.walk(handler):
            if not (isinstance(node, ast.Call) and _is_http_exception(node)):
                continue
            for detail in _detail_expressions(node):
                if _echoes(detail, handler.name):
                    failures.append(
                        (node.lineno, f"except ... as {handler.name}: detail echoes it")
                    )
    return failures


def main() -> int:
    routers = Path(__file__).resolve().parent.parent / "routers"
    if not routers.is_dir():
        print(f"routers directory not found at {routers}", file=sys.stderr)
        return 2
    backend_dir = routers.parent
    found: list[str] = []
    for path in sorted(routers.rglob("*.py")):
        rel = path.relative_to(backend_dir).as_posix()
        if rel in ALLOW_LIST:
            continue
        for line, reason in scan_source(path.read_text(encoding="utf-8")):
            found.append(f"{rel}:{line}: {reason}")
    if found:
        print("4xx detail echoes a built-in exception (use client_error_message):", file=sys.stderr)
        for entry in found:
            print(f"  {entry}", file=sys.stderr)
        return 1
    print("[OK] no 4xx detail echoes a built-in exception under backend/routers/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
