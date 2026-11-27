"""W1-06: a step's config default is declared once, in its ``config.py`` ``get_config()``.

An executor that needs a default reads ``get_config()["key"]``; it does not restate the value as
a module constant or a literal next to the key, so the panel's pre-filled value and the value a
blank or missing key gets cannot drift apart (batfish-init-snapshot had ``retain_snapshots``
default 0 next to a ``get_config`` default of 5).

Flagged, per step package (``config.py`` excluded):

* a module-level constant with ``DEFAULT`` in its name whose value equals any value of
  ``get_config()``;
* ``f(..., "key", ..., default=<literal>)`` and ``x.get("key", <literal>)`` for a key whose
  ``get_config()`` value is a declared default, whether the literal agrees with it or not;
* ``x.get("key") or <literal>`` where the literal equals ``get_config()["key"]``.

``None``, ``""``, booleans and empty containers are left out: they are the neutral "unset"
values every parser starts from, not a declared default.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Any

import pytest

_STEPS = Path(__file__).resolve().parents[2] / "workflow_steps"


def _is_declared_default(value: Any) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, (str, list, dict, tuple)) and not value:
        return False
    return isinstance(value, (str, int, float))


def _literal(node: ast.AST | None) -> tuple[bool, Any]:
    if node is None:
        return False, None
    try:
        return True, ast.literal_eval(node)
    except ValueError, TypeError, SyntaxError, MemoryError, RecursionError:
        return False, None


def _str_args(call: ast.Call) -> list[str]:
    return [
        arg.value
        for arg in call.args
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
    ]


def _is_get(call: ast.AST) -> bool:
    return (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "get"
        and bool(call.args)
        and isinstance(call.args[0], ast.Constant)
        and isinstance(call.args[0].value, str)
    )


def _receiver_get(expr: ast.AST) -> ast.Call | None:
    """The ``x.get("key")`` call at the root of ``str(x.get("key") or "").strip()`` and the like."""
    while True:
        if _is_get(expr):
            return expr  # type: ignore[return-value]
        if isinstance(expr, ast.BoolOp):
            expr = expr.values[0]
        elif isinstance(expr, ast.Call) and isinstance(expr.func, ast.Attribute):
            expr = expr.func.value
        elif isinstance(expr, ast.Call) and expr.args:
            expr = expr.args[0]
        else:
            return None


def _same(value: Any, default: Any) -> bool:
    return type(value) is type(default) and value == default


def _literal_default_sites(tree: ast.AST, defaults: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                ok, value = _literal(kw.value) if kw.arg == "default" else (False, None)
                if not ok or not _is_declared_default(value):
                    continue
                for key in _str_args(node):
                    if _is_declared_default(defaults.get(key)):
                        found.append(f"{node.lineno}:{key}=default {value!r}")
            if _is_get(node) and len(node.args) == 2:
                key = node.args[0].value  # type: ignore[attr-defined]
                ok, value = _literal(node.args[1])
                if ok and _is_declared_default(value) and _is_declared_default(defaults.get(key)):
                    found.append(f"{node.lineno}:{key}=get {value!r}")
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or) and len(node.values) == 2:
            left, right = node.values
            get_call = _receiver_get(left)
            ok, value = _literal(right)
            if get_call is not None and ok and _is_declared_default(value):
                key = get_call.args[0].value  # type: ignore[attr-defined]
                if key in defaults and _same(value, defaults[key]):
                    found.append(f"{node.lineno}:{key}=or {value!r}")
    return found


def _constant_sites(tree: ast.Module, defaults: dict[str, Any]) -> list[str]:
    found: list[str] = []
    for node in tree.body:
        if not (isinstance(node, ast.Assign) and len(node.targets) == 1):
            continue
        target = node.targets[0]
        ok, value = _literal(node.value)
        if not (isinstance(target, ast.Name) and "DEFAULT" in target.id and ok):
            continue
        if not _is_declared_default(value):
            continue
        for key, default in defaults.items():
            if _same(value, default):
                found.append(f"{node.lineno}:{target.id}=={key}")
    return found


def _violations() -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for config_file in sorted(_STEPS.glob("*/config.py")):
        package = config_file.parent.name
        defaults = importlib.import_module(f"workflow_steps.{package}.config").get_config()
        for module in sorted(config_file.parent.glob("*.py")):
            if module.name == "config.py":
                continue
            tree = ast.parse(module.read_text())
            sites = _constant_sites(tree, defaults) + _literal_default_sites(tree, defaults)
            if sites:
                result[f"{package}/{module.name}"] = sites
    return result


def test_no_step_module_restates_a_get_config_default() -> None:
    assert _violations() == {}


@pytest.mark.parametrize(
    "source",
    [
        'DEFAULT_KEY = "aci"\nx = config.get("prefix")\n',
        'parse_int_flag(config, "count", default=5)\n',
        'value = config.get("prefix", "aci")\n',
        'value = config.get("prefix") or "aci"\n',
        'value = str(config.get("prefix") or "aci")\n',
        'value = str(config.get("prefix")) or "aci"\n',
        'value = str(config.get("prefix") or "").strip() or "aci"\n',
        'parse_int_flag(config, "count", default=0)\n',
        'value = config.get("count", 7)\n',
    ],
)
def test_the_guard_sees_each_form(source: str) -> None:
    tree = ast.parse(source)
    defaults = {"prefix": "aci", "count": 5}
    assert _constant_sites(tree, defaults) + _literal_default_sites(tree, defaults)


@pytest.mark.parametrize(
    "source",
    [
        'value = config.get("prefix") or ""\n',
        'parse_int_flag(config, "count", default=get_config()["count"])\n',
        'LIMIT = 5\nparse_int_flag(config, "count")\n',
        'parse_bool_flag(config, "flag", default=False)\n',
    ],
)
def test_the_guard_leaves_these_alone(source: str) -> None:
    tree = ast.parse(source)
    defaults = {"prefix": "aci", "count": 5, "flag": False}
    assert _constant_sites(tree, defaults) + _literal_default_sites(tree, defaults) == []


def test_socket_timeout_default_is_the_common_constant() -> None:
    from workflow_steps.common.device_file_upload import DEFAULT_SOCKET_TIMEOUT

    for package in ("upload_config", "upload_binary"):
        source = (_STEPS / package / "config.py").read_text()
        assert '"socket_timeout": DEFAULT_SOCKET_TIMEOUT' in source, package
        config = importlib.import_module(f"workflow_steps.{package}.config").get_config()
        assert config["socket_timeout"] == DEFAULT_SOCKET_TIMEOUT


_FLAG_PARSERS = frozenset({"parse_bool_flag", "parse_int_flag", "parse_output_key"})


def _merged_flag_reads(tree: ast.AST) -> list[int]:
    """Lines where a flag parser reads a ``{**get_config(), ...}`` dict built in the call."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and node.args):
            continue
        name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        first = node.args[0]
        if name in _FLAG_PARSERS and isinstance(first, ast.Dict):
            unpacked = [v for k, v in zip(first.keys, first.values, strict=True) if k is None]
            if any(
                isinstance(v, ast.Call) and getattr(v.func, "id", None) == "get_config"
                for v in unpacked
            ):
                lines.append(node.lineno)
    return lines


def test_flag_parsers_read_the_step_config_not_an_inline_merge() -> None:
    """The parser's ``default`` is the fallback; merging ``get_config()`` into the argument says
    the default a second time (route-on-content did it per flag)."""
    modules = sorted(_STEPS.glob("*/*.py"))
    # One directory per step: an empty scan would pass by accident.
    assert len(modules) > 300
    found = {
        str(module.relative_to(_STEPS)): lines
        for module in modules
        if (lines := _merged_flag_reads(ast.parse(module.read_text())))
    }
    assert found == {}


def test_the_merge_scan_recognises_an_inline_merge() -> None:
    tree = ast.parse(
        'parse_bool_flag({**get_config(), **config}, "x", default=False)\n'
        'parse_bool_flag(config, "x", default=False)\n'
        "merged = {**get_config(), **config}\n"
        'parse_bool_flag(merged, "x")\n'
    )
    assert _merged_flag_reads(tree) == [1]
