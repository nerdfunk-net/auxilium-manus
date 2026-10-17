"""CF-03 step 1: a step may not turn a healthy device FAILED on its 'success' outcome (DN-A)."""

from __future__ import annotations

import pytest

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.workflow_context.guards import StepCapabilitySpec, post_step_guard

SPEC = StepCapabilitySpec(step_id="demo")


def _device(status: DeviceStatus) -> DeviceContext:
    return DeviceContext(
        id="d1",
        name="d1",
        hostname="d1",
        capabilities={Capability.IDENTITY},
        status=status,
    )


def _ctx(status: DeviceStatus) -> WorkflowContext:
    return WorkflowContext(run_id="r", workflow_id="w", devices={"d1": _device(status)})


def test_newly_failed_device_on_success_raises() -> None:
    outcomes = [StepOutcome(name="success", context=_ctx(DeviceStatus.FAILED))]
    with pytest.raises(RuntimeError, match="newly failed"):
        post_step_guard(spec=SPEC, input_context=_ctx(DeviceStatus.OK), outcomes=outcomes)


def test_already_failed_device_may_pass_through() -> None:
    outcomes = [StepOutcome(name="success", context=_ctx(DeviceStatus.FAILED))]
    post_step_guard(spec=SPEC, input_context=_ctx(DeviceStatus.FAILED), outcomes=outcomes)


def test_failed_device_on_failure_outcome_is_fine() -> None:
    outcomes = [
        StepOutcome(
            name="success", context=_ctx(DeviceStatus.OK).model_copy(update={"devices": {}})
        ),
        StepOutcome(name="failure", context=_ctx(DeviceStatus.FAILED)),
    ]
    post_step_guard(spec=SPEC, input_context=_ctx(DeviceStatus.OK), outcomes=outcomes)
