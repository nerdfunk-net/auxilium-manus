"""W1-08: the step id a module hard-codes is the id the registry knows it by."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import yaml

_STEPS = Path(__file__).resolve().parents[2] / "workflow_steps"
_NAMES = ("_STEP_ID", "STEP_ID", "_STEP")


def _registry() -> dict[str, str]:
    data = yaml.safe_load((_STEPS / "registry.yaml").read_text())
    return {p["id"]: p["directory"] for p in data["plugins"] if p.get("directory")}


def _constants(path: Path) -> dict[str, str]:
    found: dict[str, str] = {}
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id in _NAMES
                    and isinstance(node.value.value, str)
                ):
                    found[target.id] = node.value.value
    return found


def test_every_step_id_constant_equals_the_registry_id() -> None:
    wrong: dict[str, str] = {}
    for step_id, directory in _registry().items():
        for module in (_STEPS / directory).glob("*.py"):
            for name, value in _constants(module).items():
                if value != step_id:
                    wrong[f"{directory}/{module.name}:{name}"] = value
    assert wrong == {}


def test_most_steps_declare_their_id_once() -> None:
    declared = {
        step_id
        for step_id, directory in _registry().items()
        if (_STEPS / directory / "executor.py").exists()
        and _constants(_STEPS / directory / "executor.py")
    }
    # A step may take its id from a shared helper or a sibling module; the count only may rise.
    # 84 -> 82 (P-U): add-to-ise and configure-replace-config keep their id in the module they
    # were split into (parse.py, shim_jobs.py), which the other modules of the step import.
    assert len(declared) >= 82, len(declared)


# ── W1-08: one spelling, private unless shared, no stray id literals ────────────────────────────


def _step_modules() -> list[tuple[str, Path]]:
    return [
        (step_id, module)
        for step_id, directory in _registry().items()
        for module in sorted((_STEPS / directory).glob("*.py"))
    ]


def _imported_names(path: Path, package: str) -> set[str]:
    return {
        alias.name
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith(f"workflow_steps.{package}.")
        for alias in node.names
    }


def _spelling_problems(names: set[str], imported_by_siblings: set[str]) -> list[str]:
    problems: list[str] = []
    for name in sorted(names):
        if name == "_STEP":
            problems.append(f"{name} (spell it _STEP_ID)")
        elif name == "STEP_ID" and "STEP_ID" not in imported_by_siblings:
            problems.append(f"{name} (no sibling imports it: make it _STEP_ID)")
        elif name == "_STEP_ID" and "_STEP_ID" in imported_by_siblings:
            problems.append(f"{name} (a sibling imports it: make it STEP_ID)")
    return problems


def test_the_constant_is_step_id_when_shared_and_private_otherwise() -> None:
    wrong: list[str] = []
    for _step_id, module in _step_modules():
        package = module.parent.name
        siblings = [m for m in module.parent.glob("*.py") if m != module]
        imported = set().union(*(_imported_names(m, package) for m in siblings))
        wrong.extend(
            f"{package}/{module.name}:{problem}"
            for problem in _spelling_problems(set(_constants(module)), imported)
        )
    assert wrong == []


@pytest.mark.parametrize(
    ("names", "imported", "expected"),
    [
        ({"_STEP_ID"}, set(), 0),
        ({"STEP_ID"}, {"STEP_ID"}, 0),
        ({"_STEP"}, set(), 1),
        ({"STEP_ID"}, set(), 1),
        ({"_STEP_ID"}, {"_STEP_ID"}, 1),
    ],
)
def test_the_spelling_rule(names: set[str], imported: set[str], expected: int) -> None:
    assert len(_spelling_problems(names, imported)) == expected


def _id_literals(path: Path, step_id: str) -> list[int]:
    """Lines where the step's own id is an exact string literal, outside a constant definition
    and outside dict keys (``{"reachable": ...}`` is a payload key, not the id)."""
    tree = ast.parse(path.read_text())
    skip: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            skip.update(id(key) for key in node.keys if key is not None)
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id in _NAMES
        ):
            skip.add(id(node.value))
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and node.value == step_id and id(node) not in skip
    ]


def test_a_step_names_its_own_id_only_through_the_constant() -> None:
    stray = {
        f"{module.parent.name}/{module.name}": lines
        for step_id, module in _step_modules()
        if (lines := _id_literals(module, step_id))
    }
    assert stray == {}


def test_the_literal_check_sees_a_call_argument_and_skips_keys() -> None:
    source = 'x = {"demo": 1}\n_STEP_ID = "demo"\nf(step_id="demo")\n'
    path = Path(__file__).parent / "_w1_08_probe.py"
    try:
        path.write_text(source)
        assert _id_literals(path, "demo") == [3]
    finally:
        path.unlink()
