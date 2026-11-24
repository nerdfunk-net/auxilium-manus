"""The shared step-test helpers behave as documented (P-T, W13-01)."""

from __future__ import annotations

import pytest

from models.workflow_context import DeviceStatus
from tests.unit._step_helpers import (
    call_step,
    make_context,
    make_device,
    make_pool,
    make_run,
    patch_object_session,
    patch_ssh_credential,
)
from workflow_steps.common.run_session import require_session


def test_make_run_rejects_an_attribute_the_model_does_not_have() -> None:
    run = make_run(run_inputs={"a": 1})

    assert run.run_inputs == {"a": 1}
    assert run.triggered_by_id == 1
    with pytest.raises(AttributeError):
        _ = run.run_inputz


def test_make_pool_rejects_a_method_the_pool_does_not_have() -> None:
    pool = make_pool()

    assert callable(pool.run_on_device)
    with pytest.raises(AttributeError):
        _ = pool.run_on_devices


def test_make_context_keys_devices_by_id_and_keeps_metadata() -> None:
    context = make_context([make_device("a"), make_device("b", status=DeviceStatus.FAILED)], x=1)

    assert list(context.devices) == ["a", "b"]
    assert context.devices["b"].status == DeviceStatus.FAILED
    assert context.metadata == {"x": 1}
    assert context.devices["a"].hostname == "a"


@pytest.mark.asyncio
async def test_call_step_passes_the_six_keywords() -> None:
    seen: dict[str, object] = {}

    async def execute(**kwargs: object) -> list[str]:
        seen.update(kwargs)
        return ["ok"]

    context = make_context()
    assert await call_step(execute, {"k": 1}, context, node_id="n9") == ["ok"]
    assert set(seen) == {
        "config",
        "context",
        "run",
        "artifact_service",
        "node_id",
        "device_sessions",
    }
    assert seen["node_id"] == "n9"
    assert seen["context"] is context


def test_patch_helpers_replace_the_names_the_step_module_imported() -> None:
    from workflow_steps.run_command import executor as mod

    with (
        patch_ssh_credential("workflow_steps.run_command.executor") as credential,
        patch_object_session() as db,
    ):
        assert mod.resolve_ssh_credential(None, "ref", acting_user_id=3) == ("admin", "secret")
        assert require_session(make_run(), "run-command") is db
        credential.assert_called_once_with(None, "ref", acting_user_id=3)
