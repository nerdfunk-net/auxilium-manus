"""Source-agnostic helpers for steps that act on devices of one external source.

Used by the controller-backed steps (Cisco Catalyst Center, Cisco ACI): grouping devices by
``source_id``, failing a device with a structured :class:`~models.workflow_context.DeviceError`,
and splitting the result into the ``success`` / ``failure`` outcomes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from models.failure import FailureInfo
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)


@dataclass(frozen=True)
class TargetSplit:
    """Devices grouped by their source id, plus the devices a step refused outright."""

    by_source: dict[str, dict[str, DeviceContext]]
    rejected: dict[str, DeviceContext]


def failed_device(
    device: DeviceContext,
    *,
    step_id: str,
    node_id: str,
    code: str,
    message: str,
    failure: FailureInfo | None = None,
    **updates: Any,
) -> DeviceContext:
    """A copy of ``device`` marked FAILED with one more ``DeviceError``."""
    error = DeviceError(
        node_id=node_id, step_id=step_id, code=code, message=message, failure=failure
    )
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, error], **updates}
    )


def build_outcomes(
    context: WorkflowContext,
    succeeded: dict[str, DeviceContext],
    failed: dict[str, DeviceContext],
) -> list[StepOutcome]:
    outcomes = [
        StepOutcome(name="success", context=context.model_copy(update={"devices": succeeded}))
    ]
    if failed:
        outcomes.append(
            StepOutcome(name="failure", context=context.model_copy(update={"devices": failed}))
        )
    return outcomes
