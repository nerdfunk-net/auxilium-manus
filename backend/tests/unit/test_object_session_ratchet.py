"""Guard 4: a step gets its database session from ``require_session``, never from the run itself."""

from __future__ import annotations

import ast
from pathlib import Path

_STEPS = Path(__file__).resolve().parents[2] / "workflow_steps"
_ALLOWED = Path("common") / "run_session.py"


def _sites(path: Path) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and any(a.name == "object_session" for a in node.names):
            lines.append(node.lineno)
        elif isinstance(node, ast.Name | ast.Attribute):
            name = node.id if isinstance(node, ast.Name) else node.attr
            if name == "object_session":
                lines.append(node.lineno)
    return lines


def test_object_session_is_used_only_in_run_session() -> None:
    offenders = {
        str(path.relative_to(_STEPS)): _sites(path)
        for path in sorted(_STEPS.rglob("*.py"))
        if path.relative_to(_STEPS) != _ALLOWED and _sites(path)
    }
    assert offenders == {}, "use common.run_session.require_session(run, step_id) instead"
