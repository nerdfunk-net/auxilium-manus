"""Guard 2 (P-B, W1-01): no private copy of the outcome helpers in a step package.

``workflow_steps/common/device_outcomes.py`` is the one home of "fail a device", "split the
results" and "build the outcomes". A step package that defines its own ``_fail*``,
``_build_*outcomes`` or ``_partition_*`` function is a copy of it. The last legacy copies went on
2026-11-27 (W1-01); a function that only matches the name builds something else, so name it for
what it builds.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

STEPS_ROOT = Path(__file__).resolve().parents[2] / "workflow_steps"
HOME = "workflow_steps/common/device_outcomes.py"
PATTERN = re.compile(r"^_(fail|build_\w*outcomes|partition_)")


def _private_helpers() -> tuple[Counter[str], int]:
    """The offending functions per file, and how many step files were read."""
    counts: Counter[str] = Counter()
    scanned = 0
    for path in sorted(STEPS_ROOT.rglob("*.py")):
        rel = path.relative_to(STEPS_ROOT.parent).as_posix()
        if rel == HOME:
            continue
        scanned += 1
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and PATTERN.match(
                node.name
            ):
                counts[rel] += 1
    return counts, scanned


def test_no_private_outcome_helper() -> None:
    found, scanned = _private_helpers()
    assert scanned > 300, f"the scan read only {scanned} step files"
    assert not found, (
        "private _fail*/_build_*outcomes/_partition_* helper; use "
        f"workflow_steps/common/device_outcomes.py: {dict(found)}"
    )


def test_the_pattern_matches_what_it_is_meant_to() -> None:
    for name in ("_fail_device", "_failed", "_fail", "_build_outcomes", "_build_login_outcomes"):
        assert PATTERN.match(name), name
    for name in ("fail_device", "_builder", "_partitioned", "_build_sink"):
        assert not PATTERN.match(name), name
