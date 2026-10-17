"""CF-03 step 2: partial outcomes when a remote system is lost mid-loop."""

from __future__ import annotations

from sqlalchemy.exc import OperationalError

from models.failure import FailureInfo
from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from workflow_steps.common.partial_outcomes import (
    abort_outcomes,
    device_error_from_exception,
    mark_device_failed,
)


def _device(name: str) -> DeviceContext:
    return DeviceContext(id=name, name=name, hostname=name, status=DeviceStatus.OK)


def _ctx(*names: str) -> WorkflowContext:
    return WorkflowContext(run_id="r", workflow_id="w", devices={n: _device(n) for n in names})


def test_abort_splits_processed_and_remaining() -> None:
    ctx = _ctx("a", "b", "c")
    outcomes = abort_outcomes(
        context=ctx,
        node_id="n",
        step_id="s",
        done_ok={"a": ctx.devices["a"]},
        done_failed={},
        message="lost",
        failure=None,
    )
    by = {o.name: o for o in outcomes}
    assert list(by["success"].context.devices) == ["a"]
    assert sorted(by["failure"].context.devices) == ["b", "c"]
    assert by["failure"].context.devices["b"].errors[-1].code == "remote_system_lost"
    assert by["success"].context.metadata["n.processed"] == ["a"]


def test_abort_with_nothing_processed_is_all_failure() -> None:
    ctx = _ctx("a", "b")
    failure = FailureInfo(phase="api", kind="timeout")
    outcomes = abort_outcomes(
        context=ctx,
        node_id="n",
        step_id="s",
        done_ok={},
        done_failed={},
        message="m",
        failure=failure,
    )
    by = {o.name: o for o in outcomes}
    assert by["success"].context.devices == {}
    assert sorted(by["failure"].context.devices) == ["a", "b"]
    assert by["failure"].failure == failure


def test_abort_does_not_mutate_input_context() -> None:
    ctx = _ctx("a", "b")
    before = ctx.model_dump(mode="json")
    abort_outcomes(
        context=ctx, node_id="n", step_id="s", done_ok={}, done_failed={}, message="m", failure=None
    )
    assert ctx.model_dump(mode="json") == before


def test_mark_device_failed_appends_error() -> None:
    device = mark_device_failed(_device("a"), node_id="n", step_id="s", code="c", message="m")
    assert device.status == DeviceStatus.FAILED
    assert device.errors[-1].code == "c"


def test_device_error_from_exception_hides_driver_text() -> None:
    exc = OperationalError(
        "INSERT INTO t (password) VALUES (%(p)s)", {"p": "hunter2"}, Exception("x")
    )
    error = device_error_from_exception(exc, node_id="n", step_id="s")
    assert error.message == "OperationalError"
    assert error.code == "operationalerror"
    assert error.failure is not None and error.failure.kind == "internal_error"
    assert "hunter2" not in str(error) and "INSERT" not in str(error)


def test_device_error_from_exception_keeps_authored_messages() -> None:
    error = device_error_from_exception(ValueError("pattern is required"), node_id="n", step_id="s")
    assert error.message == "pattern is required"
    missing = device_error_from_exception(
        FileNotFoundError("no such artifact"), node_id="n", step_id="s"
    )
    assert missing.message == "no such artifact"


def test_device_error_from_exception_keeps_an_attached_classification() -> None:
    class Classified(Exception):
        failure = FailureInfo(phase="api", kind="timeout")

    error = device_error_from_exception(Classified("boom"), node_id="n", step_id="s")
    assert error.failure is not None and error.failure.kind == "timeout"
    assert error.message == "Classified"
