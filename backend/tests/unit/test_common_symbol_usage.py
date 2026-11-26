"""Guard 8 (W2-15, W12): every public function and class of ``workflow_steps/common`` has a user.

A user is production code (anything under ``backend/`` except ``tests/``) that imports the
symbol (``from workflow_steps.common.X import s``, relative forms included), reaches it through a
module alias (``from workflow_steps.common import X`` + ``X.s``) or names it inside its own
module. A symbol only tests use is dead code with a safety net: delete it, make it private, or
list it below with the reason. The list may only shrink; an entry that gained a user, went
private or was deleted must be removed.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
COMMON = BACKEND / "workflow_steps" / "common"
PACKAGE = "workflow_steps.common"
_SKIPPED_DIRS = {"tests", ".venv", "__pycache__"}

# "<module>.<symbol>" -> why it has no production user yet.
WITHOUT_PRODUCTION_USER: dict[str, str] = {}


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(BACKEND).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imported_module(path: Path, node: ast.ImportFrom) -> str:
    if not node.level:
        return node.module or ""
    base = _module_name(path).split(".")
    if path.name != "__init__.py":
        base.pop()
    base = base[: len(base) - (node.level - 1)]
    return ".".join([*base, *([node.module] if node.module else [])])


def public_symbols() -> set[str]:
    found: set[str] = set()
    for path in sorted(COMMON.glob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
                if not node.name.startswith("_"):
                    found.add(f"{path.stem}.{node.name}")
    return found


def uses_in(path: Path, source: str) -> Iterator[str]:
    """Every ``<common module>.<name>`` the file at *path* (with *source*) uses."""
    tree = ast.parse(source)
    module = _module_name(path)
    own = module.removeprefix(f"{PACKAGE}.") if module.startswith(f"{PACKAGE}.") else None
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported = _imported_module(path, node)
            if imported.startswith(f"{PACKAGE}."):
                stem = imported.removeprefix(f"{PACKAGE}.")
                yield from (f"{stem}.{alias.name}" for alias in node.names)
            elif imported == PACKAGE:
                aliases.update({a.asname or a.name: a.name for a in node.names})
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(f"{PACKAGE}.") and alias.asname:
                    aliases[alias.asname] = alias.name.removeprefix(f"{PACKAGE}.")
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            if node.value.id in aliases:
                yield f"{aliases[node.value.id]}.{node.attr}"
        elif own is not None and isinstance(node, ast.Name):
            yield f"{own}.{node.id}"


def used_symbols() -> set[str]:
    used: set[str] = set()
    for path in sorted(BACKEND.rglob("*.py")):
        if not _SKIPPED_DIRS.intersection(path.relative_to(BACKEND).parts):
            used.update(uses_in(path, path.read_text()))
    return used


def test_every_public_common_symbol_has_a_production_user() -> None:
    unused = public_symbols() - used_symbols() - set(WITHOUT_PRODUCTION_USER)
    assert unused == set(), (
        "public workflow_steps/common symbol without a production user: delete it, make it "
        f"private, or list it with the reason: {sorted(unused)}"
    )


def test_the_list_is_not_stale() -> None:
    stale = set(WITHOUT_PRODUCTION_USER) - (public_symbols() - used_symbols())
    assert stale == set(), f"remove these entries (now used, private or gone): {sorted(stale)}"


def _uses(rel: str, source: str) -> set[str]:
    return set(uses_in(BACKEND / rel, source))


def test_an_absolute_import_is_a_use() -> None:
    source = "from workflow_steps.common.step_flags import parse_output_key as p"
    assert _uses("workflow_steps/x/executor.py", source) == {"step_flags.parse_output_key"}


def test_a_relative_import_from_a_step_package_is_a_use() -> None:
    source = "from ..common.step_flags import parse_output_key"
    assert _uses("workflow_steps/x/executor.py", source) == {"step_flags.parse_output_key"}


def test_a_relative_import_inside_common_is_a_use() -> None:
    source = "from .step_flags import require_text"
    assert "step_flags.require_text" in _uses("workflow_steps/common/other.py", source)


def test_a_module_alias_attribute_is_a_use() -> None:
    source = "from workflow_steps.common import step_flags as f\nf.require_text(c)"
    assert "step_flags.require_text" in _uses("services/x.py", source)


def test_an_import_as_alias_attribute_is_a_use() -> None:
    source = "import workflow_steps.common.step_flags as f\nf.require_text(c)"
    assert "step_flags.require_text" in _uses("services/x.py", source)


def test_a_name_inside_its_own_module_is_a_use() -> None:
    source = "def helper(): ...\nx = helper()"
    assert "attribute_write.helper" in _uses("workflow_steps/common/attribute_write.py", source)


def test_a_name_in_another_module_is_not_a_use() -> None:
    source = "def helper(): ...\nx = helper()"
    assert _uses("workflow_steps/x/executor.py", source) == set()


def test_an_import_from_another_package_is_not_a_use() -> None:
    source = "from services.workflow_context.node_result import set_node_result"
    assert _uses("workflow_steps/x/executor.py", source) == set()


def test_private_and_nested_definitions_are_not_public() -> None:
    symbols = public_symbols()
    assert "step_flags.parse_output_key" in symbols
    assert not any(name.split(".", 1)[1].startswith("_") for name in symbols)
