#!/usr/bin/env python3
"""
Regression check: workflow-step flags are parsed by ``workflow_steps/common/step_flags.py`` only.

``bool(config.get("x"))`` is true for the string ``"false"``, ``config.get("x") is True`` is false
for the string ``"true"``, and every private ``_parse_bool`` re-implements the rule differently.
Use ``parse_bool_flag(config, key, default=...)`` / ``parse_int_flag(...)``.

Flags, under ``backend/workflow_steps`` and ``backend/services/execution``:

* ``bool(<config-like>.get(<key>, ...))``, the key may be a variable
* ``int(<config-like>.get(<key>, ...))`` / ``float(...)``: ``int(7.9)`` and ``int(True)`` succeed
* ``int(<anything naming git_repository_id>)``: use ``parse_repository_id``
* ``<config-like>.get("key") is True`` / ``is False``
* ``<text>.strip().lower() in {"true", "yes", ...}``: a hand-written boolean spelling table
* a function named like a private boolean parser (``_parse_bool``, ``parse_bool``, ``_bool``, ...)

A line that carries the comment ``check_flag_parsing: ok`` (with the reason) is skipped: use it
only for a value that is not step config (for example a resolved per-device value that is
already parsed strictly).

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


def _is_config_get(node: ast.expr, *, constant_key: bool = True) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and _config_like(node.func.value)
        and bool(node.args)
        and (
            not constant_key
            or (isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str))
        )
    )


_BOOL_WORDS = frozenset({"true", "yes", "on", "false", "no", "off"})


def _names_repository_id(node: ast.expr) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and "repository_id" in child.id:
            return True
        if (
            isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and "git_repository_id" in child.value
        ):
            return True
    return False


def _is_bool_spelling_table(node: ast.Compare) -> bool:
    if not isinstance(node.ops[0], (ast.In, ast.NotIn)):
        return False
    table = node.comparators[0]
    if not isinstance(table, (ast.Set, ast.Tuple, ast.List)):
        return False
    words = {
        e.value for e in table.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)
    }
    return bool(words & _BOOL_WORDS)


_OPT_OUT = "check_flag_parsing: ok"


def violations_in(source: str, filename: str = "<string>") -> list[tuple[int, str]]:
    found = _violations_in(source, filename)
    lines = source.splitlines()
    return [(line, message) for line, message in found if _OPT_OUT not in lines[line - 1]]


def _violations_in(source: str, filename: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source, filename=filename)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "bool"
            and len(node.args) == 1
            and _is_config_get(node.args[0], constant_key=False)
        ):
            found.append((node.lineno, "bool(config.get(...)): use parse_bool_flag"))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"int", "float"}
            and len(node.args) == 1
            and _is_config_get(node.args[0], constant_key=False)
        ):
            found.append((node.lineno, f"{node.func.id}(config.get(...)): use parse_int_flag"))
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "int"
            and len(node.args) == 1
            and _names_repository_id(node.args[0])
        ):
            found.append((node.lineno, "int(git_repository_id): use parse_repository_id"))
        elif isinstance(node, ast.Compare) and len(node.ops) == 1 and _is_bool_spelling_table(node):
            found.append(
                (node.lineno, "hand-written true/false spelling table: use parse_bool_flag")
            )
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
