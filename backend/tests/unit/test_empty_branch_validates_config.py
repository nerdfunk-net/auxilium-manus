"""P-S (D2, W11-12 / W1-10): a step validates its config before it looks at the devices.

An empty branch is a no-op ``success``, but a config the step can never run with is reported on
every run, not only on the one where devices arrive. The AST guard below pins the steps whose
``execute`` still returns for an empty device list before it reads ``config`` (it may only fall);
the behavioural test runs each migrated step with an unusable config and no devices.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path
from typing import Any

import pytest

from tests.unit._step_helpers import call_step, make_context, make_run

STEPS_ROOT = Path(__file__).resolve().parents[2] / "workflow_steps"

# Steps whose empty-device guard runs before the config is read. Only falls; delete at zero.
LEGACY_GUARD_BEFORE_CONFIG: frozenset[str] = frozenset()

# Step -> a config the step cannot run with (each raises ValueError even with no devices).
UNUSABLE_CONFIG: dict[str, dict[str, Any]] = {
    "add_pyats_testbed": {},
    "collect_client_data": {"collect_ip_address": False, "collect_mac_address": False},
    "compare_data": {"content_source": "nope"},
    "decrypt_attribute": {},
    "deploy_rendered_template": {},
    "discover_network": {"follow_neighbors": True},
    "encrypt_attribute": {},
    "filter_output": {},
    "get_catalyst_center_client_data": {"lookback_hours": 0},
    "get_device_configs": {"config_format": "nope"},
    "get_device_location": {},
    "get_from_db": {},
    "get_nautobot_attributes": {},
    "get_pyats_running_config": {"output_key": "1bad"},
    "list_contains": {},
    "login_successful": {"credential_source": "run_param"},
    "merge_config": {},
    "merge_content": {"content_source": "nope"},
    "render_jinja_template": {},
    "route_on_content": {},
    "route_to_agent": {},
    "run_command": {"parser": "genie"},
    "store_artifact": {},
    "store_in_db": {},
    "update_attribute": {"bogus": 1},
    "update_content": {},
}


def _guard_before_config() -> set[str]:
    found: set[str] = set()
    for path in sorted(STEPS_ROOT.glob("*/executor.py")):
        tree = ast.parse(path.read_text())
        fns = [
            n
            for n in tree.body
            if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name == "execute"
        ]
        if not fns:
            continue
        body = fns[0].body
        guard = next(
            (
                i
                for i, st in enumerate(body)
                if isinstance(st, ast.If)
                and isinstance(st.test, ast.UnaryOp)
                and isinstance(st.test.op, ast.Not)
                and ast.unparse(st.test.operand).endswith("context.devices")
            ),
            None,
        )
        if guard is None:
            continue
        first_config = next(
            (
                i
                for i, st in enumerate(body)
                if "config" in {n.id for n in ast.walk(st) if isinstance(n, ast.Name)}
            ),
            None,
        )
        if first_config is None or guard < first_config:
            found.add(path.parent.name)
    return found


def test_no_new_step_guards_before_it_reads_its_config() -> None:
    actual = _guard_before_config()
    assert actual <= LEGACY_GUARD_BEFORE_CONFIG, (
        "a step returns for an empty device list before it reads its config; parse first: "
        f"{sorted(actual - LEGACY_GUARD_BEFORE_CONFIG)}"
    )


def test_guard_ratchet_list_is_not_stale() -> None:
    stale = LEGACY_GUARD_BEFORE_CONFIG - _guard_before_config()
    assert not stale, f"delete these entries of LEGACY_GUARD_BEFORE_CONFIG: {sorted(stale)}"


@pytest.mark.asyncio
@pytest.mark.parametrize("step", sorted(UNUSABLE_CONFIG))
async def test_an_unusable_config_is_reported_on_an_empty_branch(step: str) -> None:
    module = importlib.import_module(f"workflow_steps.{step}.executor")
    with pytest.raises(ValueError):
        await call_step(module.execute, UNUSABLE_CONFIG[step], make_context(), run=make_run())
