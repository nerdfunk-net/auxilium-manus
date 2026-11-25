"""``start-workflow``: the async seams call the child-run facade in a thread (W10-12)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.execution.child_runs import CallingRunMissingError, ChildTarget
from workflow_steps.start_workflow import executor as mod

pytestmark = pytest.mark.asyncio


async def test_check_target_inspects_what_the_facade_loaded() -> None:
    target = ChildTarget(name="child", canvas_nodes=[{"id": "n"}], static_attributes=[])
    with (
        patch.object(mod, "load_child_target", return_value=target) as load,
        patch.object(mod, "_inspect_target", return_value=["warn"]) as inspect,
    ):
        result = await mod._check_target(
            parent_run_id=7, workflow_id=42, run_inputs={"a": 1}, devices_input="devs"
        )

    load.assert_called_once_with(7, 42)
    inspect.assert_called_once_with("child", [{"id": "n"}], [], {"a": 1}, "devs")
    assert result == ["warn"]


async def test_a_missing_calling_run_names_the_step() -> None:
    with patch.object(mod, "load_child_target", side_effect=CallingRunMissingError):
        with pytest.raises(ValueError, match="^start-workflow: the calling run no longer exists"):
            await mod._check_target(
                parent_run_id=7, workflow_id=42, run_inputs={}, devices_input="d"
            )
    with patch.object(mod, "start_child", side_effect=CallingRunMissingError):
        with pytest.raises(ValueError, match="^start-workflow: the calling run no longer exists"):
            await mod._start_child(parent_run_id=7, workflow_id=42, run_inputs={})


async def test_start_snapshot_and_cancel_checks_forward_their_arguments() -> None:
    with patch.object(mod, "start_child", return_value=99) as start:
        assert await mod._start_child(parent_run_id=7, workflow_id=42, run_inputs={"x": 1}) == 99
    start.assert_called_once_with(7, 42, {"x": 1})

    snapshot = MagicMock()
    with patch.object(mod, "child_snapshot", return_value=snapshot) as snap:
        assert await mod._snapshot(5) is snapshot
    snap.assert_called_once_with(5)

    with patch.object(mod, "parent_cancelled", return_value=True) as cancelled:
        assert await mod._parent_cancelled(7) is True
    cancelled.assert_called_once_with(7)
