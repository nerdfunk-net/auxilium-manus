"""W1-08: the step id a module hard-codes is the id the registry knows it by."""

from __future__ import annotations

import ast
from pathlib import Path

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
    assert len(declared) >= 84, len(declared)
