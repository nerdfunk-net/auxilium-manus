"""Per-device failure and outcome construction for the run-command step."""

from __future__ import annotations

from typing import Any

from models.failure import FailureInfo
from models.workflow_context import (
    CommandResult,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from workflow_steps.run_command.constants import STEP_ID


def fail_device(
    *,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    code: str,
    message: str,
    command_results: dict[str, list[CommandResult]] | None = None,
    failure: FailureInfo | None = None,
) -> tuple[str, DeviceContext, bool]:
    err = DeviceError(
        node_id=node_id,
        step_id=STEP_ID,
        code=code,
        message=message,
        failure=failure,
    )
    update: dict[str, Any] = {
        "status": DeviceStatus.FAILED,
        "errors": [*device.errors, err],
    }
    if command_results is not None:
        update["command_results"] = command_results
    failed = device.model_copy(update=update)
    return device_id, failed, False


def build_outcomes(
    *,
    context: WorkflowContext,
    success_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
    command_count: int,
) -> list[StepOutcome]:
    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
            summary=f"ran {command_count} command(s) on {len(success_devices)} device(s)",
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed_devices}),
                summary=f"{len(failed_devices)} device(s) failed",
            )
        )
    return outcomes
