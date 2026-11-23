"""``collect_facts`` (the shared driver of the ACI and Catalyst Center fact steps), W8-01.

A controller error is turned into an entry by each step's ``fact()``; anything else raised by
``collect`` (a bug, a cancelled sub-task, a parsing error) escapes ``asyncio.gather`` and aborts
every device of every controller.
"""

from __future__ import annotations

from typing import Any

import pytest

from models.workflow_context import DeviceStatus
from tests.unit._step_helpers import make_context, make_device, strict_xfail
from workflow_steps.common.device_outcomes import TargetSplit
from workflow_steps.common.fact_entries import collect_facts, ok_entry


async def _run(collect: Any) -> list[Any]:
    devices = {d: make_device(d) for d in ("a", "b")}
    return await collect_facts(
        step_id="s",
        context=make_context(devices.values()),
        node_id="n",
        output_key="k",
        collect=collect,
        split=TargetSplit(by_source={"src": devices}, rejected={}),
        credentials={"src": "creds"},
        error_code="e",
    )


@pytest.mark.asyncio
async def test_every_device_is_collected() -> None:
    async def collect(_creds: Any, _state: Any, device_id: str, _device: Any) -> dict[str, Any]:
        return {"f": ok_entry(device_id)}

    outcomes = await _run(collect)

    assert [o.name for o in outcomes] == ["success"]
    assert set(outcomes[0].context.devices) == {"a", "b"}


@strict_xfail("W8-01", "an unexpected exception from collect() aborts every device")
@pytest.mark.asyncio
async def test_an_unexpected_error_fails_only_that_device() -> None:
    async def collect(_creds: Any, _state: Any, device_id: str, _device: Any) -> dict[str, Any]:
        if device_id == "a":
            raise KeyError("unexpected controller payload")
        return {"f": ok_entry(device_id)}

    outcomes = await _run(collect)

    by_name = {o.name: o.context.devices for o in outcomes}
    assert set(by_name["success"]) == {"b"}
    assert set(by_name["failure"]) == {"a"}
    assert by_name["failure"]["a"].status == DeviceStatus.FAILED
