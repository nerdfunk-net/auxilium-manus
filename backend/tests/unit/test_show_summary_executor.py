"""show-summary is a pass-through marker: it forwards the context and counts the devices."""

from __future__ import annotations

import pytest

from models.workflow_context import DeviceStatus
from tests.unit._step_helpers import call_step, make_context, make_device
from workflow_steps.show_summary.executor import execute


@pytest.mark.asyncio
async def test_empty_context_succeeds_with_a_zero_count() -> None:
    outcomes = await call_step(execute, {}, make_context(), node_id="sum")

    assert [o.name for o in outcomes] == ["success"]
    assert outcomes[0].context.metadata["sum.show_summary"] == {"device_count": 0}
    assert outcomes[0].context.devices == {}


@pytest.mark.asyncio
async def test_one_device_is_forwarded_unchanged_and_counted() -> None:
    device = make_device("d1")
    context = make_context([device], earlier="kept")

    outcomes = await call_step(execute, {}, context, node_id="sum")

    result = outcomes[0].context
    assert result.devices["d1"] == device
    assert result.metadata["sum.show_summary"] == {"device_count": 1}
    assert result.metadata["earlier"] == "kept"
    assert "sum.show_summary" not in context.metadata  # the input context is not mutated


@pytest.mark.asyncio
async def test_failed_devices_are_counted_and_the_step_still_succeeds() -> None:
    context = make_context([make_device("a"), make_device("b", status=DeviceStatus.FAILED)])

    outcomes = await call_step(execute, {}, context, node_id="sum")

    assert [o.name for o in outcomes] == ["success"]
    assert outcomes[0].context.metadata["sum.show_summary"] == {"device_count": 2}
    assert outcomes[0].context.devices["b"].status == DeviceStatus.FAILED
