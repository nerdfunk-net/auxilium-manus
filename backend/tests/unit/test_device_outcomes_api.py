"""P-B: the one outcome API in ``common/device_outcomes.py`` (W1-01).

The module is the single home of "fail a device" (``mark_device_failed`` builds the error,
``fail_device_with_error`` takes one already built) and "build the outcomes".
``partial_outcomes`` keeps ``device_error_from_exception`` and ``abort_outcomes``.
"""

from __future__ import annotations

import pytest

from models.failure import FailureInfo
from models.workflow_context import DeviceError, DeviceStatus, StepOutcome
from tests.unit._step_helpers import make_context, make_device
from workflow_steps.common import device_outcomes, partial_outcomes
from workflow_steps.common.device_outcomes import (
    build_outcomes,
    fail_device_with_error,
    mark_device_failed,
    outcomes_from_buckets,
    whole_step_failure,
)


def _by_name(outcomes: list[StepOutcome]) -> dict[str, StepOutcome]:
    return {o.name: o for o in outcomes}


def test_one_implementation_of_mark_device_failed() -> None:
    assert partial_outcomes.mark_device_failed is mark_device_failed


@pytest.mark.parametrize(
    ("module", "name"),
    [
        (device_outcomes, "failed_device"),  # the older alias of mark_device_failed (P-X4)
        (device_outcomes, "DeviceResult"),  # never adopted outside tests (P-X4)
        (device_outcomes, "partition_results"),
        (partial_outcomes, "fail_device_with_error"),  # moved to device_outcomes
    ],
)
def test_the_leftover_names_are_gone(module: object, name: str) -> None:
    assert not hasattr(module, name)


def test_fail_device_with_error_appends_the_given_error() -> None:
    error = DeviceError(node_id="n", step_id="s", code="c", message="m")
    first = mark_device_failed(make_device("a"), node_id="n0", step_id="s0", code="z", message="")

    failed = fail_device_with_error(first, error, hostname="renamed")

    assert failed.status == DeviceStatus.FAILED
    assert failed.errors == [first.errors[0], error]
    assert failed.hostname == "renamed"
    assert len(first.errors) == 1  # input copy untouched


def test_mark_device_failed_is_fail_device_with_error_on_a_built_error() -> None:
    failure = FailureInfo(phase="api", kind="timeout")
    error = DeviceError(node_id="n", step_id="s", code="c", message="m", failure=failure)
    device = make_device("a")

    built = mark_device_failed(
        device, node_id="n", step_id="s", code="c", message="m", failure=failure, hostname="h"
    )

    made = built.errors[-1]
    assert made.model_dump(exclude={"occurred_at"}) == error.model_dump(exclude={"occurred_at"})
    assert built == fail_device_with_error(device, made, hostname="h")


def test_mark_device_failed_appends_error_and_keeps_history() -> None:
    first = mark_device_failed(make_device("a"), node_id="n", step_id="s", code="one", message="m1")
    second = mark_device_failed(
        first,
        node_id="n2",
        step_id="s2",
        code="two",
        message="m2",
        failure=FailureInfo(phase="api", kind="timeout"),
    )
    assert second.status == DeviceStatus.FAILED
    assert [e.code for e in second.errors] == ["one", "two"]
    assert second.errors[1].failure == FailureInfo(phase="api", kind="timeout")
    assert first.errors[0].code == "one" and len(first.errors) == 1  # input copy untouched


def test_mark_device_failed_applies_extra_updates() -> None:
    device = mark_device_failed(
        make_device("a"), node_id="n", step_id="s", code="c", message="m", hostname="renamed"
    )
    assert device.hostname == "renamed"
    assert device.status == DeviceStatus.FAILED


def test_build_outcomes_success_always_failure_only_when_needed() -> None:
    context = make_context([make_device("a")])
    only_ok = build_outcomes(context, {"a": context.devices["a"]}, {})
    assert [o.name for o in only_ok] == ["success"]
    empty = build_outcomes(context, {}, {})
    assert [o.name for o in empty] == ["success"] and empty[0].context.devices == {}


def test_build_outcomes_summaries_and_metadata() -> None:
    context = make_context([make_device("a"), make_device("b")])
    outcomes = _by_name(
        build_outcomes(
            context,
            {"a": context.devices["a"]},
            {"b": context.devices["b"]},
            metadata={"n.count": 1},
            success_summary="1 ok",
            failure_summary="1 failed",
        )
    )
    assert outcomes["success"].summary == "1 ok"
    assert outcomes["failure"].summary == "1 failed"
    assert outcomes["success"].context.metadata["n.count"] == 1
    assert outcomes["failure"].context.metadata["n.count"] == 1
    assert "n.count" not in context.metadata  # the input context is never mutated


def test_build_outcomes_default_signature_is_unchanged() -> None:
    context = make_context([make_device("a")])
    outcomes = build_outcomes(context, {"a": context.devices["a"]}, {})
    assert outcomes[0].summary is None
    assert outcomes[0].context.metadata == context.metadata


def test_outcomes_from_buckets_always_emits_every_handle() -> None:
    context = make_context([make_device("a"), make_device("b")])
    outcomes = outcomes_from_buckets(
        context,
        {"success": {"a": context.devices["a"]}, "failure": {}},
        metadata={"n.counts": {"success": 1, "failure": 0}},
    )
    assert [o.name for o in outcomes] == ["success", "failure"]
    by = _by_name(outcomes)
    assert list(by["success"].context.devices) == ["a"]
    assert by["failure"].context.devices == {}
    assert by["failure"].context.metadata["n.counts"] == {"success": 1, "failure": 0}


def test_outcomes_from_buckets_keeps_the_order_of_the_buckets() -> None:
    context = make_context([make_device("a")])
    names = ["clean", "dirty", "failure"]
    outcomes = outcomes_from_buckets(context, {n: {} for n in names})
    assert [o.name for o in outcomes] == names


def test_whole_step_failure_fails_every_device_with_one_error() -> None:
    context = make_context([make_device("a"), make_device("b")])
    failure = FailureInfo(phase="api", kind="server_error")
    outcomes = whole_step_failure(
        context,
        node_id="n",
        step_id="s",
        code="remote_down",
        message="down",
        failure=failure,
        metadata={"n.error": "down"},
    )
    by = _by_name(outcomes)
    assert list(by) == ["success", "failure"]
    assert by["success"].context.devices == {}
    assert by["failure"].failure == failure
    assert by["failure"].summary == "down"
    for device in by["failure"].context.devices.values():
        assert device.status == DeviceStatus.FAILED
        assert device.errors[-1].code == "remote_down"
        assert device.errors[-1].failure == failure
    assert by["failure"].context.metadata["n.error"] == "down"
    assert all(d.status == DeviceStatus.OK for d in context.devices.values())


def test_whole_step_failure_without_devices_still_leaves_on_failure() -> None:
    context = make_context([])
    outcomes = whole_step_failure(context, node_id="n", step_id="s", code="c", message="m")
    assert [o.name for o in outcomes] == ["success", "failure"]
    assert outcomes[1].context.devices == {}


def test_whole_step_failure_empty_handles_are_configurable() -> None:
    context = make_context([make_device("a")])
    outcomes = whole_step_failure(
        context,
        node_id="n",
        step_id="s",
        code="c",
        message="m",
        empty_handles=("clean", "dirty"),
    )
    assert [o.name for o in outcomes] == ["clean", "dirty", "failure"]
    assert outcomes[0].context.devices == {} and outcomes[1].context.devices == {}


# ---- device_error_from_exception, per exception class (W13 section 4) ----------------------


@pytest.mark.parametrize(
    ("exc", "keeps_text"),
    [
        (ValueError("bad path 'x'"), True),
        (FileNotFoundError("no such file"), True),
        (RuntimeError("driver said: password=hunter2"), False),
        (KeyError("secret-key"), False),
        (OSError("/home/user/.ssh/id_rsa: denied"), False),
        (TimeoutError("took too long"), False),
        (TypeError("unsupported operand"), False),
    ],
)
def test_device_error_from_exception_text_per_class(exc: Exception, keeps_text: bool) -> None:
    error = partial_outcomes.device_error_from_exception(exc, node_id="n", step_id="s")
    assert error.code == type(exc).__name__.lower()
    assert error.message == (str(exc) if keeps_text else type(exc).__name__)
    assert error.failure is not None  # every class gets a closed-vocabulary record
    if not keeps_text:
        assert "hunter2" not in error.message and "id_rsa" not in error.message


def test_device_error_from_exception_keeps_the_carried_classification() -> None:
    carried = FailureInfo(phase="connect", kind="timeout")

    class _Classified(RuntimeError):
        failure = carried

    error = partial_outcomes.device_error_from_exception(
        _Classified("text"), node_id="n", step_id="s"
    )
    assert error.failure == carried
    assert error.message == "_Classified"


def test_device_error_from_exception_follows_the_cause_chain() -> None:
    carried = FailureInfo(phase="api", kind="auth_failed")

    class _Client(Exception):
        failure = carried

    try:
        try:
            raise _Client("inner")
        except _Client as inner:
            raise RuntimeError("outer") from inner
    except RuntimeError as outer:
        error = partial_outcomes.device_error_from_exception(outer, node_id="n", step_id="s")
    assert error.failure == carried
    assert error.message == "RuntimeError"


def test_unclassified_exception_gets_an_internal_record() -> None:
    error = partial_outcomes.device_error_from_exception(
        RuntimeError("x"), node_id="n", step_id="s"
    )
    assert error.failure == FailureInfo(
        phase="internal", kind="internal_error", exception_type="RuntimeError"
    )


def test_device_error_keep_text_extends_the_kept_classes() -> None:
    class Sanitised(Exception):
        pass

    kept = partial_outcomes.device_error_from_exception(
        Sanitised("fixed sentence"), node_id="n", step_id="s", keep_text=(Sanitised,)
    )
    hidden = partial_outcomes.device_error_from_exception(
        Sanitised("fixed sentence"), node_id="n", step_id="s"
    )

    assert kept.message == "fixed sentence"
    assert hidden.message == "Sanitised"


def test_run_command_has_no_private_outcome_module() -> None:
    # run-command fails devices and builds its outcomes through this module (P-X4).
    import importlib.util

    assert importlib.util.find_spec("workflow_steps.run_command.outcomes") is None
