#!/usr/bin/env python3
"""
Regression check: workflow-step flags are parsed by ``workflow_steps/common/step_flags.py`` only.

``bool(config.get("x"))`` is true for the string ``"false"``, ``config.get("x") is True`` is false
for the string ``"true"``, and every private ``_parse_bool`` re-implements the rule differently.
Use ``parse_bool_flag(config, key, default=...)`` / ``parse_int_flag(...)``.

Flags, under ``backend/workflow_steps`` and ``backend/services/execution``:

* ``bool(<config-like>.get("key", ...))``
* ``<config-like>.get("key") is True`` / ``is False``
* a function named like a private boolean parser (``_parse_bool``, ``parse_bool``, ``_bool``, ...)

Exit status ``1`` on any violation. Usage::

    python backend/scripts/check_flag_parsing.py [path ...]
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

_PARSER_NAMES = frozenset(
    {"_parse_bool", "parse_bool", "_bool", "_as_bool", "_parse_bool_flag", "_to_bool"}
)
_ALLOWED_FILES = frozenset({"step_flags.py"})


def _config_like(node: ast.expr) -> bool:
    name = node.id if isinstance(node, ast.Name) else None
    if name is None:
        return False
    lowered = name.lower()
    return "config" in lowered or "cfg" in lowered or lowered == "conf"


def _is_config_get(node: ast.expr) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and _config_like(node.func.value)
        and bool(node.args)
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    )


def violations_in(source: str, filename: str = "<string>") -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "bool"
            and len(node.args) == 1
            and _is_config_get(node.args[0])
        ):
            found.append((node.lineno, "bool(config.get(...)): use parse_bool_flag"))
        elif (
            isinstance(node, ast.Compare)
            and len(node.ops) == 1
            and isinstance(node.ops[0], (ast.Is, ast.IsNot))
            and _is_config_get(node.left)
            and isinstance(node.comparators[0], ast.Constant)
            and isinstance(node.comparators[0].value, bool)
        ):
            found.append((node.lineno, "config.get(...) is True/False: use parse_bool_flag"))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name in _PARSER_NAMES
        ):
            found.append((node.lineno, f"private boolean parser {node.name}(): use step_flags"))
    return found


def _roots() -> list[Path]:
    backend = Path(__file__).resolve().parent.parent
    return [backend / "workflow_steps", backend / "services" / "execution"]


def main(argv: list[str]) -> int:
    roots = [Path(arg) for arg in argv] if argv else _roots()
    hits: list[tuple[Path, int, str]] = []
    for root in roots:
        files = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in files:
            if path.name in _ALLOWED_FILES:
                continue
            try:
                source = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:  # noqa: S112  # not a text file
                continue
            hits.extend((path, line, message) for line, message in violations_in(source, str(path)))

    if not hits:
        print("[OK] every step flag is parsed by workflow_steps/common/step_flags.py")
        return 0
    print("[FAIL] step flags parsed outside step_flags.py:")
    for path, line, message in hits:
        print(f"  {path}:{line}: {message}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
