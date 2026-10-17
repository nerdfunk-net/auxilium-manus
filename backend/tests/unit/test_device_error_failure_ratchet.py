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
    "workflow_steps/batfish_extract_facts/executor.py": 1,
    "workflow_steps/batfish_validate_facts/executor.py": 4,
    "workflow_steps/common/pyats_batch.py": 1,
    "workflow_steps/common/secret_paths.py": 1,
    "workflow_steps/compare_pyats_snapshot/executor.py": 1,
    "workflow_steps/config_to_attributes/executor.py": 1,
    "workflow_steps/decrypt_attribute/executor.py": 1,
    "workflow_steps/encrypt_attribute/executor.py": 1,
    "workflow_steps/filter_output/executor.py": 1,
    "workflow_steps/get_ise_devices/executor.py": 1,
    "workflow_steps/get_ise_tacacs_key/executor.py": 1,
    "workflow_steps/get_pyats_running_config/executor.py": 1,
    "workflow_steps/get_pyats_snapshot/executor.py": 1,
    "workflow_steps/get_virtual_chassis/stack.py": 1,
    "workflow_steps/list_contains/executor.py": 1,
    "workflow_steps/open_change_request/executor.py": 1,
    "workflow_steps/parse_cisco_config/executor.py": 1,
    "workflow_steps/reachable/executor.py": 2,
    "workflow_steps/read_config/executor.py": 1,
    "workflow_steps/read_from_file/executor.py": 1,
    "workflow_steps/split_virtual_chassis/executor.py": 1,
    "workflow_steps/store_artifact/executor.py": 2,
    "workflow_steps/store_in_db/executor.py": 1,
    "workflow_steps/undefined_and_unused/executor.py": 1,
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
