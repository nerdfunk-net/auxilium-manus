"""``collect_facts`` (the shared driver of the ACI and Catalyst Center fact steps), W8-01.

A controller error is turned into an entry by each step's ``fact()``; anything else raised by
``collect`` (a bug, a cancelled sub-task, a parsing error) escapes ``asyncio.gather`` and aborts
every device of every controller.
"""

from __future__ import annotations

from typing import Any

import pytest

from models.workflow_context import DeviceStatus
from tests.unit._step_helpers import make_context, make_device
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
    error = by_name["failure"]["a"].errors[-1]
    assert error.message == "KeyError"  # the class name, never the controller payload text
    assert error.failure is not None


async def _run_two_sources(collect: Any, prepare: Any) -> list[Any]:
    one = {"a": make_device("a")}
    two = {"b": make_device("b"), "c": make_device("c")}
    return await collect_facts(
        step_id="s",
        context=make_context([*one.values(), *two.values()]),
        node_id="n",
        output_key="k",
        collect=collect,
        split=TargetSplit(by_source={"src1": one, "src2": two}, rejected={}),
        credentials={"src1": "creds1", "src2": "creds2"},
        error_code="e",
        prepare=prepare,
    )


_SECRET = "controller payload with 10.9.9.9 and a token"


@pytest.mark.asyncio
async def test_a_prepare_that_raises_fails_only_the_devices_of_that_controller() -> None:
    collected: list[str] = []

    async def prepare(creds: str) -> str:
        if creds == "creds1":
            raise RuntimeError(_SECRET)
        return f"state-{creds}"

    async def collect(_creds: Any, state: Any, device_id: str, _device: Any) -> dict[str, Any]:
        collected.append(device_id)
        return {"f": ok_entry(state)}

    outcomes = await _run_two_sources(collect, prepare)

    by_name = {o.name: o.context.devices for o in outcomes}
    assert set(by_name["success"]) == {"b", "c"}
    assert set(by_name["failure"]) == {"a"}
    assert sorted(collected) == ["b", "c"]
    failed = by_name["failure"]["a"]
    assert failed.status == DeviceStatus.FAILED
    error = failed.errors[-1]
    assert error.message == "RuntimeError"
    assert _SECRET not in str(failed.errors)
    assert error.failure is not None
    assert error.failure.kind == "internal_error"
    assert error.step_id == "s"
    assert error.node_id == "n"


@pytest.mark.asyncio
async def test_every_prepare_failing_fails_every_device_without_collecting() -> None:
    async def prepare(_creds: str) -> str:
        raise KeyError("x")

    async def collect(*_a: Any) -> dict[str, Any]:
        raise AssertionError("collect must not run for a controller whose prepare failed")

    outcomes = await _run_two_sources(collect, prepare)

    assert [o.name for o in outcomes] == ["success", "failure"]
    assert outcomes[0].context.devices == {}
    assert set(outcomes[1].context.devices) == {"a", "b", "c"}
    assert all(d.errors[-1].message == "KeyError" for d in outcomes[1].context.devices.values())


@pytest.mark.asyncio
async def test_a_cancelled_prepare_is_not_swallowed() -> None:
    import asyncio

    async def prepare(_creds: str) -> str:
        raise asyncio.CancelledError

    async def collect(*_a: Any) -> dict[str, Any]:
        return {}

    with pytest.raises(asyncio.CancelledError):
        await _run_two_sources(collect, prepare)
