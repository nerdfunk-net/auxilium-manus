"""A step marks a device FAILED only through ``common/device_outcomes.py``.

``mark_device_failed`` (fields) and ``fail_device_with_error`` (a built ``DeviceError``) are the one
way to fail a device; both take further fields of the copy (``parsed=...``). A step that builds
``device.model_copy(update={"status": DeviceStatus.FAILED, ...})`` itself is a copy of them (15 such
sites were folded into the helpers on 2026-11-27; there is no allow-list).
"""

from __future__ import annotations

import ast
from pathlib import Path

STEPS_ROOT = Path(__file__).resolve().parents[2] / "workflow_steps"
HOME = STEPS_ROOT / "common" / "device_outcomes.py"


def failed_copies(tree: ast.AST) -> list[int]:
    """Lines of ``x.model_copy(update={..., "status": <...>.FAILED, ...})`` calls."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "model_copy"):
            continue
        for keyword in node.keywords:
            if keyword.arg != "update" or not isinstance(keyword.value, ast.Dict):
                continue
            for key, value in zip(keyword.value.keys, keyword.value.values, strict=True):
                if (
                    isinstance(key, ast.Constant)
                    and key.value == "status"
                    and isinstance(value, ast.Attribute)
                    and value.attr == "FAILED"
                ):
                    lines.append(node.lineno)
    return lines


def test_no_step_builds_a_failed_copy_itself() -> None:
    modules = [path for path in sorted(STEPS_ROOT.rglob("*.py")) if path != HOME]
    # The step packages live under one root: an empty scan would pass by accident.
    assert len(modules) > 300
    found = {
        str(path.relative_to(STEPS_ROOT)): lines
        for path in modules
        if (lines := failed_copies(ast.parse(path.read_text())))
    }
    assert found == {}


def test_the_home_still_builds_it() -> None:
    assert failed_copies(ast.parse(HOME.read_text()))


def test_the_scan_recognises_a_failed_copy() -> None:
    tree = ast.parse(
        'device.model_copy(update={"status": DeviceStatus.FAILED, "errors": errors})\n'
        'device.model_copy(update={"status": DeviceStatus.OK})\n'
        'mark_device_failed(device, node_id="n", step_id="s", code="c", message="m")\n'
    )
    assert failed_copies(tree) == [1]
