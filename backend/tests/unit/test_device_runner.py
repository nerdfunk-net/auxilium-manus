"""P-C: ``common/device_runner.py::run_per_device`` (D1, W11-01).

One boundary for "try -> map the exception -> fail the device": a work function returns the
updated device, returns ``Fail`` for a device-level failure, or raises. Unexpected exceptions
fail that device only (class name, never the text), ``AbortRun`` stops a sequential run, and
cancellation always passes through.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from models.failure import FailureInfo
from models.workflow_context import DeviceContext, DeviceStatus
from tests.unit._step_helpers import make_context, make_device
from workflow_steps.common.device_runner import AbortRun, Fail, run_per_device

_SECRET = "hunter2-never-stored"


def _ctx(n: int = 5) -> Any:
    return make_context([make_device(str(i)) for i in range(n)])


def _touched(device: DeviceContext) -> DeviceContext:
    return device.model_copy(update={"hostname": device.hostname + "!"})


@pytest.mark.asyncio
async def test_every_device_ok_keeps_context_order() -> None:
    async def work(device_id: str, device: DeviceContext) -> DeviceContext:
        await asyncio.sleep(0.01 * (5 - int(device_id)))  # finish in reverse order
        return _touched(device)

    batch = await run_per_device(_ctx(), work, node_id="n", step_id="s")

    assert list(batch.ok) == ["0", "1", "2", "3", "4"]
    assert batch.failed == {} and batch.aborted is None
    assert batch.ok["2"].hostname == "2!"


@pytest.mark.asyncio
async def test_returned_fail_marks_the_device_with_code_message_and_failure() -> None:
    failure = FailureInfo(phase="api", kind="not_found")

    async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        if device_id == "1":
            return Fail("not_found", "no record", failure)
        return device

    batch = await run_per_device(_ctx(3), work, node_id="n", step_id="s")

    assert list(batch.ok) == ["0", "2"] and list(batch.failed) == ["1"]
    error = batch.failed["1"].errors[-1]
    assert (error.code, error.message, error.failure) == ("not_found", "no record", failure)
    assert (error.node_id, error.step_id) == ("n", "s")
    assert batch.failed["1"].status == DeviceStatus.FAILED


@pytest.mark.asyncio
async def test_unexpected_exception_fails_that_device_and_hides_its_text() -> None:
    async def work(device_id: str, device: DeviceContext) -> DeviceContext:
        if device_id == "1":
            raise RuntimeError(f"driver said pw={_SECRET}")
        return device

    batch = await run_per_device(_ctx(3), work, node_id="n", step_id="s")

    assert list(batch.ok) == ["0", "2"]
    error = batch.failed["1"].errors[-1]
    assert error.code == "runtimeerror" and error.message == "RuntimeError"
    assert error.failure is not None and error.failure.kind == "internal_error"
    assert _SECRET not in repr(batch.failed["1"].errors)


@pytest.mark.asyncio
async def test_value_error_keeps_the_steps_own_text() -> None:
    async def work(device_id: str, device: DeviceContext) -> DeviceContext:
        raise ValueError("step says: bad value")

    batch = await run_per_device(_ctx(1), work, node_id="n", step_id="s")

    assert batch.failed["0"].errors[-1].message == "step says: bad value"


@pytest.mark.asyncio
async def test_a_classified_exception_keeps_its_failure_record() -> None:
    carried = FailureInfo(phase="connect", kind="timeout")

    class _Timeout(Exception):
        failure = carried

    async def work(device_id: str, device: DeviceContext) -> DeviceContext:
        raise _Timeout("x")

    batch = await run_per_device(_ctx(1), work, node_id="n", step_id="s")

    assert batch.failed["0"].errors[-1].failure == carried


@pytest.mark.asyncio
async def test_error_history_of_the_device_is_kept() -> None:
    first = make_device("0")

    async def one(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return Fail("one", "m1")

    ctx = make_context([first])
    batch1 = await run_per_device(ctx, one, node_id="n", step_id="s")
    ctx2 = make_context([batch1.failed["0"]])
    batch2 = await run_per_device(ctx2, one, node_id="n2", step_id="s2")

    assert [e.node_id for e in batch2.failed["0"].errors] == ["n", "n2"]


@pytest.mark.asyncio
async def test_concurrent_by_default() -> None:
    running = 0
    peak = 0

    async def work(device_id: str, device: DeviceContext) -> DeviceContext:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.02)
        running -= 1
        return device

    await run_per_device(_ctx(5), work, node_id="n", step_id="s")

    assert peak == 5


@pytest.mark.asyncio
@pytest.mark.parametrize(("limit", "expected_peak"), [(1, 1), (2, 2)])
async def test_concurrency_limit(limit: int, expected_peak: int) -> None:
    running = 0
    peak = 0

    async def work(device_id: str, device: DeviceContext) -> DeviceContext:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.01)
        running -= 1
        return device

    batch = await run_per_device(_ctx(5), work, node_id="n", step_id="s", concurrency=limit)

    assert peak == expected_peak and len(batch.ok) == 5


@pytest.mark.asyncio
async def test_sequential_runs_in_order() -> None:
    seen: list[str] = []

    async def work(device_id: str, device: DeviceContext) -> DeviceContext:
        seen.append(device_id)
        return device

    await run_per_device(_ctx(4), work, node_id="n", step_id="s", concurrency=1)

    assert seen == ["0", "1", "2", "3"]


@pytest.mark.asyncio
async def test_a_failure_does_not_stop_the_next_device() -> None:
    async def work(device_id: str, device: DeviceContext) -> DeviceContext:
        if device_id == "0":
            raise RuntimeError("boom")
        return device

    batch = await run_per_device(_ctx(3), work, node_id="n", step_id="s", concurrency=1)

    assert list(batch.failed) == ["0"] and list(batch.ok) == ["1", "2"]


@pytest.mark.asyncio
async def test_abort_stops_a_sequential_run_and_keeps_what_was_done() -> None:
    failure = FailureInfo(phase="api", kind="server_error")
    seen: list[str] = []

    async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        seen.append(device_id)
        if device_id == "1":
            return Fail("x", "bad")
        if device_id == "2":
            raise AbortRun("lost connection", failure)
        return device

    batch = await run_per_device(_ctx(5), work, node_id="n", step_id="s", concurrency=1)

    assert seen == ["0", "1", "2"]  # 3 and 4 never started
    assert list(batch.ok) == ["0"] and list(batch.failed) == ["1"]
    assert batch.aborted is not None
    assert batch.aborted.message == "lost connection" and batch.aborted.failure == failure


@pytest.mark.asyncio
async def test_abort_needs_a_sequential_run() -> None:
    async def work(device_id: str, device: DeviceContext) -> DeviceContext:
        raise AbortRun("lost")

    with pytest.raises(RuntimeError, match="AbortRun"):
        await run_per_device(_ctx(2), work, node_id="n", step_id="s", concurrency=2)


@pytest.mark.asyncio
async def test_only_limits_the_devices_that_run() -> None:
    seen: list[str] = []

    async def work(device_id: str, device: DeviceContext) -> DeviceContext:
        seen.append(device_id)
        return device

    batch = await run_per_device(
        _ctx(4), work, node_id="n", step_id="s", concurrency=1, only={"1", "3"}
    )

    assert seen == ["1", "3"] and list(batch.ok) == ["1", "3"]


@pytest.mark.asyncio
async def test_cancellation_is_never_swallowed() -> None:
    started = asyncio.Event()

    async def work(device_id: str, device: DeviceContext) -> DeviceContext:
        started.set()
        await asyncio.sleep(10)
        return device

    task = asyncio.create_task(run_per_device(_ctx(2), work, node_id="n", step_id="s"))
    await started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_cancellation_inside_a_sequential_work_passes_through() -> None:
    async def work(device_id: str, device: DeviceContext) -> DeviceContext:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await run_per_device(_ctx(2), work, node_id="n", step_id="s", concurrency=1)


@pytest.mark.asyncio
async def test_input_context_is_not_mutated() -> None:
    ctx = _ctx(2)
    before = ctx.model_dump(mode="json")

    async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return Fail("c", "m") if device_id == "0" else _touched(device)

    await run_per_device(ctx, work, node_id="n", step_id="s")

    assert ctx.model_dump(mode="json") == before


@pytest.mark.asyncio
async def test_concurrency_below_one_is_a_programming_error() -> None:
    async def work(device_id: str, device: DeviceContext) -> DeviceContext:
        return device

    with pytest.raises(ValueError, match="concurrency"):
        await run_per_device(_ctx(1), work, node_id="n", step_id="s", concurrency=0)


@pytest.mark.asyncio
async def test_fail_can_carry_the_device_the_error_is_recorded_on() -> None:
    async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return Fail("diff_mismatch", "differs", device=_touched(device))

    batch = await run_per_device(_ctx(1), work, node_id="n", step_id="s")

    failed = batch.failed["0"]
    assert failed.hostname == "0!"  # the work's own copy, not the input device
    assert failed.status == DeviceStatus.FAILED
    assert failed.errors[-1].code == "diff_mismatch"


@pytest.mark.asyncio
async def test_log_label_writes_a_start_and_a_finish_line_per_device(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return Fail("c", "m") if device_id == "1" else device

    ctx = make_context([make_device("0", hostname="10.0.0.1"), make_device("1")], run_id="run-9")
    with caplog.at_level("INFO", logger="workflow_steps.common.device_runner"):
        await run_per_device(ctx, work, node_id="n", step_id="s", log_label="my-step")

    lines = [r.getMessage() for r in caplog.records]
    assert "my-step device 1/2 id=0 host=10.0.0.1: connecting run_id=run-9" in lines
    assert "my-step device 1/2 id=0 host=10.0.0.1: ok run_id=run-9" in lines
    assert any("device 2/2 id=1" in line and ": failed run_id=run-9" in line for line in lines)


@pytest.mark.asyncio
async def test_no_log_label_no_device_lines(caplog: pytest.LogCaptureFixture) -> None:
    async def work(device_id: str, device: DeviceContext) -> DeviceContext:
        return device

    with caplog.at_level("INFO", logger="workflow_steps.common.device_runner"):
        await run_per_device(_ctx(2), work, node_id="n", step_id="s")

    assert caplog.records == []
