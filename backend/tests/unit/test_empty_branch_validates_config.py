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
from unittest.mock import patch

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


# R4-02: a step that works per device returns for an empty device list before it opens the DB
# session or resolves a credential, so an empty branch succeeds without touching the vault.
# Calls that count as a credential lookup: ``require_session`` and any ``resolve_*credential*``.
# The steps below are exempt: they make the devices (inventory) or act on the run as a whole,
# not on ``context.devices``. Two-sided: an entry that no longer looks up first is stale.
WHOLE_STEP_CREDENTIAL_FIRST: frozenset[str] = frozenset(
    {
        "backup_aci_config",
        "batfish_init_snapshot",
        "compare_aci_subnets",
        "get_from_agent",
        "get_from_user",
        "get_ise_devices",
        "get_nautobot_devices",
        "get_virtual_chassis",
        "notify_mattermost",
        "notify_on_error",
        "send_mail",
    }
)

# Step -> a config it can run with; with no devices it must answer success and look nothing up.
USABLE_CONFIG_NO_LOOKUP: dict[str, dict[str, Any]] = {
    "upload_binary": {
        "git_repository_id": 1,
        "source_path": "img.bin",
        "file_system": "flash:",
        "destination_filename": "img.bin",
    },
    "upload_config": {
        "destination_filename": "a.cfg",
        "file_system": "flash:",
        "source_step_node_id": "n1",
    },
}


def _is_lookup(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
    return name == "require_session" or (name.startswith("resolve_") and "credential" in name)


def _is_empty_guard(statement: ast.stmt) -> bool:
    return (
        isinstance(statement, ast.If)
        and isinstance(statement.test, ast.UnaryOp)
        and isinstance(statement.test.op, ast.Not)
        and ast.unparse(statement.test.operand).endswith("context.devices")
    )


def _looks_up_first(source: str) -> bool | None:
    """For an executor's source: ``None`` when ``execute`` looks nothing up, else whether the
    first lookup comes before the empty-device return (or there is no such return)."""
    tree = ast.parse(source)
    body = next(
        (
            n.body
            for n in tree.body
            if isinstance(n, ast.AsyncFunctionDef | ast.FunctionDef) and n.name == "execute"
        ),
        None,
    )
    if body is None:
        return None
    lookup = next(
        (i for i, st in enumerate(body) if any(_is_lookup(n) for n in ast.walk(st))), None
    )
    if lookup is None:
        return None
    guard = next((i for i, st in enumerate(body) if _is_empty_guard(st)), None)
    return guard is None or lookup < guard


def _lookup_before_guard() -> tuple[set[str], int]:
    """Steps whose ``execute`` looks up a credential before the empty-device return (or with
    none), and how many executors look one up at all (the scan must not be empty)."""
    found: set[str] = set()
    scanned = 0
    for path in sorted(STEPS_ROOT.glob("*/executor.py")):
        first = _looks_up_first(path.read_text())
        if first is None:
            continue
        scanned += 1
        if first:
            found.add(path.parent.name)
    return found, scanned


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("db = require_session(run, 'x')\nif not context.devices:\n    return []", True),
        ("if not context.devices:\n    return []\ndb = require_session(run, 'x')", False),
        ("creds = SRC.resolve_credentials(db, 's')", True),
        ("user = resolve_ssh_credential(db, ref)\nif not context.devices:\n    return []", True),
        ("if not context.devices:\n    return []\nresolve_ssh_credential(db, ref)", False),
        ("x = resolve_output_key(config)", None),
    ],
)
def test_the_lookup_scan_reads_the_order(body: str, expected: bool | None) -> None:
    source = "async def execute(*, config, context, run):\n" + "".join(
        f"    {line}\n" for line in body.splitlines()
    )
    assert _looks_up_first(source) is expected


def test_a_per_device_step_returns_for_no_devices_before_any_lookup() -> None:
    found, scanned = _lookup_before_guard()
    assert scanned >= 20, f"the scan found only {scanned} executors with a lookup"
    assert found <= WHOLE_STEP_CREDENTIAL_FIRST, (
        "a step opens the session or resolves a credential before its empty-device return: "
        f"{sorted(found - WHOLE_STEP_CREDENTIAL_FIRST)}"
    )


def test_the_whole_step_exemptions_are_not_stale() -> None:
    found, _ = _lookup_before_guard()
    stale = WHOLE_STEP_CREDENTIAL_FIRST - found
    assert not stale, f"delete these entries of WHOLE_STEP_CREDENTIAL_FIRST: {sorted(stale)}"


@pytest.mark.asyncio
@pytest.mark.parametrize("step", sorted(USABLE_CONFIG_NO_LOOKUP))
async def test_an_empty_branch_succeeds_without_a_lookup(step: str) -> None:
    module = importlib.import_module(f"workflow_steps.{step}.executor")
    refuse = AssertionError("looked up with no devices")
    with (
        patch.object(module, "require_session", side_effect=refuse),
        patch.object(module, "resolve_ssh_credential", side_effect=refuse),
    ):
        outcomes = await call_step(
            module.execute, USABLE_CONFIG_NO_LOOKUP[step], make_context(), run=make_run()
        )
    assert [outcome.name for outcome in outcomes] == ["success"]


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
