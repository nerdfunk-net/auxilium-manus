"""A step that fails a device records why as a ``FailureInfo`` (doc/claude/backend.md).

``DeviceError.failure`` is optional, so omitting it is legal but loses the structured cause the run
viewer and the AI assistant use. This ratchet pins how many ``DeviceError(...)`` calls per step
file still omit ``failure=``. Fix a site and lower its number (delete the entry at zero); never
raise a number or add a file. Plain config errors with no applicable failure code are the usual
reason a site stays here.
"""

from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

STEPS_ROOT = Path(__file__).resolve().parents[2] / "workflow_steps"

LEGACY_WITHOUT_FAILURE: dict[str, int] = {
    "workflow_steps/config_to_attributes/executor.py": 1,
    "workflow_steps/filter_output/executor.py": 1,
    "workflow_steps/get_virtual_chassis/stack.py": 1,
}


def _calls_without_failure() -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in sorted(STEPS_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if name == "DeviceError" and not any(kw.arg == "failure" for kw in node.keywords):
                counts[path.relative_to(STEPS_ROOT.parent).as_posix()] += 1
    return counts


def test_no_new_device_error_without_failure() -> None:
    actual = _calls_without_failure()
    grown = {
        f: (LEGACY_WITHOUT_FAILURE.get(f, 0), n)
        for f, n in actual.items()
        if n > LEGACY_WITHOUT_FAILURE.get(f, 0)
    }
    assert not grown, f"DeviceError without failure= added (allowed, found): {grown}"


def test_ratchet_list_is_not_stale() -> None:
    actual = _calls_without_failure()
    stale = {
        f: (n, actual.get(f, 0)) for f, n in LEGACY_WITHOUT_FAILURE.items() if actual.get(f, 0) < n
    }
    assert not stale, f"lower these entries in LEGACY_WITHOUT_FAILURE (listed, found): {stale}"
