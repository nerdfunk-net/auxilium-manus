"""Guard 2 (P-B): private copies of the outcome helpers may only disappear.

``workflow_steps/common/device_outcomes.py`` is the one home of "fail a device", "partition the
results" and "build the outcomes" (W1-01). A step package that defines its own ``_fail*``,
``_build_*outcomes`` or ``_partition_*`` function is a copy of it. The legacy copies are pinned
per file and fall as the families migrate (P-C); never raise a number or add a file. When a count
reaches zero, delete the entry.
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from pathlib import Path

STEPS_ROOT = Path(__file__).resolve().parents[2] / "workflow_steps"
HOME = "workflow_steps/common/device_outcomes.py"
PATTERN = re.compile(r"^_(fail|build_\w*outcomes|partition_)")

LEGACY_PRIVATE_HELPERS: dict[str, int] = {
    "workflow_steps/add_ip_to_nautobot/executor.py": 2,
    "workflow_steps/add_nautobot_metadata/executor.py": 2,
    "workflow_steps/add_to_ise/executor.py": 1,
    "workflow_steps/add_to_nautobot/executor.py": 2,
    "workflow_steps/collect_client_data/executor.py": 1,
    "workflow_steps/common/device_file_upload.py": 1,
    "workflow_steps/compare_data/executor.py": 1,
    "workflow_steps/contact_the_ai/executor.py": 1,
    "workflow_steps/enrich_attributes/executor.py": 1,
    "workflow_steps/get_aci_policy/executor.py": 1,
    "workflow_steps/get_next_free_ip/executor.py": 3,
    "workflow_steps/list_contains/executor.py": 1,
    "workflow_steps/parse_cisco_config/executor.py": 2,
    "workflow_steps/remove_from_nautobot/executor.py": 2,
    "workflow_steps/render_jinja_template/executor.py": 2,
    "workflow_steps/route_on_content/executor.py": 1,
    "workflow_steps/run_command/exec_mode.py": 1,
    "workflow_steps/undefined_and_unused/executor.py": 1,
    "workflow_steps/update_config_context/executor.py": 2,
    "workflow_steps/update_nautobot_device/executor.py": 2,
}


def _private_helpers() -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in sorted(STEPS_ROOT.rglob("*.py")):
        rel = path.relative_to(STEPS_ROOT.parent).as_posix()
        if rel == HOME:
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and PATTERN.match(
                node.name
            ):
                counts[rel] += 1
    return counts


def test_no_new_private_outcome_helper() -> None:
    actual = _private_helpers()
    grown = {
        f: (LEGACY_PRIVATE_HELPERS.get(f, 0), n)
        for f, n in actual.items()
        if n > LEGACY_PRIVATE_HELPERS.get(f, 0)
    }
    assert not grown, (
        "private _fail*/_build_*outcomes/_partition_* helper added; use "
        f"workflow_steps/common/device_outcomes.py (allowed, found): {grown}"
    )


def test_ratchet_list_is_not_stale() -> None:
    actual = _private_helpers()
    stale = {
        f: (n, actual.get(f, 0)) for f, n in LEGACY_PRIVATE_HELPERS.items() if actual.get(f, 0) < n
    }
    assert not stale, f"lower these entries (listed, found); delete at zero: {stale}"


def test_the_pattern_matches_what_it_is_meant_to() -> None:
    for name in ("_fail_device", "_failed", "_fail", "_build_outcomes", "_build_login_outcomes"):
        assert PATTERN.match(name), name
    for name in ("fail_device", "_builder", "_partitioned", "_build_sink"):
        assert not PATTERN.match(name), name
