"""W7-03 (P-C step 4): one device's (or one chunk's) unexpected error never fails the step.

A malformed shim answer, a sealed password that cannot be decrypted, an artifact that cannot be
stored or read each used to fail every device (the exception left ``asyncio.gather``). They now
fail the device or the chunk they belong to and keep the results of the others.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.workflow_context import DeviceContext
from services.artifacts import InMemoryArtifactService
from services.workflow_context.secret_fields import SEALED_MARKER, seal_secret
from tests.unit._step_helpers import call_step, make_context, make_device, make_run
from tests.unit.test_batfish_validate_facts_executor import _context_with_snapshot, _device
from workflow_steps.batfish_validate_facts import executor as validate_mod
from workflow_steps.common import pyats_batch
from workflow_steps.compare_pyats_snapshot import executor as compare_mod
from workflow_steps.get_pyats_running_config import executor as running_mod
from workflow_steps.get_pyats_snapshot import executor as snapshot_mod

_SECRET = "s3cr3t-library-text 10.9.9.9"


def _testbed_device(device_id: str, *, password: Any = None) -> DeviceContext:
    return make_device(
        device_id,
        attribute_bags={
            "pyats_testbed": {
                "pyats_source_id": "lab",
                "host": f"10.0.0.{len(device_id)}",
                "os": "ios",
                "username": "admin",
                "password": password if password is not None else seal_secret("secret"),
            }
        },
    )


def _failed(outcomes: list[Any], device_id: str):
    return next(o for o in outcomes if o.name == "failure").context.devices[device_id]


# --- run_batched -----------------------------------------------------------------------------


async def _batched(run_job: AsyncMock, group: list[tuple[str, dict[str, Any]]], chunk_size: int):
    shim = MagicMock()
    shim.limits = AsyncMock(side_effect=RuntimeError("no limits"))
    shim.run_job = run_job
    return await pyats_batch.run_batched(
        shim=shim,
        credentials=MagicMock(),
        operation="parse",
        commands=["show running-config"],
        device_group=group,
        chunk_size=chunk_size,
    )


@pytest.mark.asyncio
async def test_a_chunk_with_a_malformed_answer_fails_only_that_chunk() -> None:
    answers = [
        json.JSONDecodeError(_SECRET, "doc", 0),
        {"results": {"b": {"success": True, "commands": {}}}},
    ]
    results = await _batched(
        AsyncMock(side_effect=answers), [("a", {"name": "a"}), ("b", {"name": "b"})], chunk_size=1
    )

    assert results["a"]["success"] is False
    assert results["a"]["error"] == "JSONDecodeError"
    assert _SECRET not in str(results)
    assert results["b"]["success"] is True


@pytest.mark.asyncio
async def test_an_answer_that_is_not_a_mapping_fails_its_chunk() -> None:
    results = await _batched(AsyncMock(return_value=["not", "a", "dict"]), [("a", {})], 5)

    assert results["a"]["success"] is False
    assert results["a"]["error"] == "AttributeError"
    assert results["a"]["commands"] == {}
    assert results["a"]["failure"].kind == "internal_error"


@pytest.mark.asyncio
async def test_a_sealed_password_that_cannot_be_decrypted_fails_that_device_only() -> None:
    unreadable = {SEALED_MARKER: True, "v": 1, "ct": "x"}
    good, bad = _testbed_device("good"), _testbed_device("bad", password=unreadable)

    groups, failures = pyats_batch.validate_and_group_devices(
        devices={"good": good, "bad": bad},
        node_id="n",
        step_id="s",
        source_credentials={"lab": MagicMock()},
        source_errors={},
    )

    assert [device_id for device_id, _ in groups["lab"]] == ["good"]
    error = failures["bad"].errors[-1]
    assert error.code == "credential_unreadable"
    assert error.failure is not None


# --- get-pyats-snapshot ----------------------------------------------------------------------


class _FailingStore(InMemoryArtifactService):
    def __init__(self, failing_device: str) -> None:
        super().__init__()
        self.failing_device = failing_device

    async def store(self, **kwargs: Any):  # type: ignore[override]
        if kwargs.get("device_id") == self.failing_device:
            raise OSError(_SECRET)
        return await super().store(**kwargs)


@pytest.mark.asyncio
async def test_a_failing_artifact_store_fails_that_snapshot_device_only() -> None:
    answers = {
        "results": {
            name: {
                "success": True,
                "commands": {"bgp": {"parsed": {"x": 1}, "error": None}},
            }
            for name in ("a", "b")
        }
    }
    shim = MagicMock()
    shim.limits = AsyncMock(side_effect=RuntimeError("no limits"))
    shim.run_job = AsyncMock(return_value=answers)
    mod = "workflow_steps.get_pyats_snapshot.executor"
    with (
        patch(f"{mod}.object_session", return_value=MagicMock()),
        patch("workflow_steps.common.pyats_batch.PyATSSourceConfigService") as config_service,
        patch(f"{mod}.service_factory") as factory,
    ):
        config_service.return_value.resolve_credentials.return_value = MagicMock()
        factory.get_pyats_app_service.return_value = shim
        outcomes = await call_step(
            snapshot_mod.execute,
            {"features": ["bgp"], "output_key": "snap"},
            make_context([_testbed_device("a"), _testbed_device("b")]),
            run=make_run(),
            artifact_service=_FailingStore("b"),
        )

    by_name = {o.name: set(o.context.devices) for o in outcomes}
    assert by_name == {"success": {"a"}, "failure": {"b"}}
    error = _failed(outcomes, "b").errors[-1]
    assert error.message == "OSError"
    assert error.failure is not None


@pytest.mark.asyncio
async def test_running_config_marks_a_shim_failure_with_its_text_and_code() -> None:
    device = make_device("a")
    result = running_mod._shape_result(
        device_id="a",
        device=device,
        output_key="k",
        result={"success": False, "error": "device refused login"},
    )

    assert result.code == "device_error" and result.message == "device refused login"


# --- compare-pyats-snapshot -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_unexpected_error_for_one_device_does_not_fail_the_comparison_step() -> None:
    async def compare_one(*, device_id: str, device: DeviceContext, **_: Any):
        if device_id == "b":
            raise OSError(_SECRET)
        return device_id, device, "match", {"device_id": device_id}

    mod = "workflow_steps.compare_pyats_snapshot.executor"
    with (
        patch(f"{mod}.object_session", return_value=MagicMock()),
        patch(f"{mod}.resolve_source_credentials", return_value=({}, {})),
        patch(f"{mod}.shim_concurrency", create=True, new=AsyncMock(return_value=2)),
        patch("workflow_steps.common.pyats_batch.shim_concurrency", AsyncMock(return_value=2)),
        patch(f"{mod}.service_factory"),
        patch(f"{mod}._compare_one_device", side_effect=compare_one),
    ):
        outcomes = await call_step(
            compare_mod.execute,
            {
                "features": ["bgp"],
                "source_step_node_id": "snap",
                "filename_template": "{device.name}",
            },
            make_context([make_device("a"), make_device("b")]),
            run=make_run(),
        )

    by_name = {o.name: o.context for o in outcomes}
    assert set(by_name["match"].devices) == {"a"}
    error = by_name["failure"].devices["b"].errors[-1]
    assert error.message == "OSError"
    assert error.failure is not None
    assert by_name["match"].metadata["node-1.comparisons"] == [{"device_id": "a"}]
    assert by_name["match"].metadata["node-1.comparison_counts"] == {
        "match": 1,
        "mismatch": 0,
        "failure": 1,
    }


# --- batfish-validate-facts -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_an_error_while_preparing_one_device_fails_that_device_only() -> None:
    async def prepare(*, device: DeviceContext, **_: Any):
        if device.name == "b":
            raise OSError(_SECRET)
        return device.name, {"tacacs": "10.0.0.1"}

    mod = "workflow_steps.batfish_validate_facts.executor"
    batfish = MagicMock()
    batfish.validate_facts = AsyncMock(return_value={})
    with (
        patch(f"{mod}.service_factory") as factory,
        patch(f"{mod}._prepare_contribution", side_effect=prepare),
    ):
        factory.get_batfish_app_service.return_value = batfish
        outcomes = await call_step(
            validate_mod.execute,
            {"facts_source": "field", "fact_key": "tacacs", "fact_value": "10.0.0.1"},
            _context_with_snapshot({"a": _device("a", "a"), "b": _device("b", "b")}),
            run=make_run(),
        )

    by_name = {o.name: o.context for o in outcomes}
    assert set(by_name["match"].devices) == {"a"}
    error = by_name["failure"].devices["b"].errors[-1]
    assert error.message == "OSError"
    assert error.failure is not None


@pytest.mark.asyncio
async def test_devices_are_compared_at_most_as_many_at_once_as_the_shim_runs() -> None:
    running = peak = 0

    async def compare_one(*, device_id: str, device: DeviceContext, **_: Any):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return device_id, device, "match", None

    mod = "workflow_steps.compare_pyats_snapshot.executor"
    with (
        patch(f"{mod}.object_session", return_value=MagicMock()),
        patch(f"{mod}.resolve_source_credentials", return_value=({}, {})),
        patch("workflow_steps.common.pyats_batch.shim_concurrency", AsyncMock(return_value=2)),
        patch(f"{mod}.service_factory"),
        patch(f"{mod}._compare_one_device", side_effect=compare_one),
    ):
        outcomes = await call_step(
            compare_mod.execute,
            {
                "features": ["bgp"],
                "source_step_node_id": "snap",
                "filename_template": "{device.name}",
            },
            make_context([make_device(f"d{i}") for i in range(6)]),
            run=make_run(),
        )

    assert len(outcomes[0].context.devices) == 6
    assert peak == 2
