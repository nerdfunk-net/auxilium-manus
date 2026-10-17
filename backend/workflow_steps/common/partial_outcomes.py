"""Outcome helpers for per-device failure routing (DN-A).

No business logic: a failed device is marked ``FAILED`` with a ``DeviceError`` and leaves a step
through ``failure``; when a remote system is lost mid-loop the devices already processed keep
their result and every device not yet processed fails with the transport cause.
"""

from __future__ import annotations

from models.failure import FailureInfo, failure_from_exception
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)


def mark_device_failed(
    device: DeviceContext,
    *,
    node_id: str,
    step_id: str,
    code: str,
    message: str,
    failure: FailureInfo | None = None,
) -> DeviceContext:
    error = DeviceError(
        node_id=node_id, step_id=step_id, code=code, message=message, failure=failure
    )
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, error]}
    )


def device_error_from_exception(
    exc: BaseException, *, node_id: str, step_id: str
) -> DeviceError:
    """A closed-vocabulary record plus a message that never contains driver or SQL text.

    ``ValueError`` and ``FileNotFoundError`` messages are written by the steps themselves and are
    safe to keep; any other exception (a database driver, an HTTP client, ...) is reduced to its
    class name, because its text can carry SQL, bound parameters or credentials.
    """
    failure = failure_from_exception(exc) or FailureInfo(
        phase="internal", kind="internal_error", exception_type=type(exc).__name__
    )
    message = str(exc) if isinstance(exc, (ValueError, FileNotFoundError)) else type(exc).__name__
    return DeviceError(
        node_id=node_id,
        step_id=step_id,
        code=type(exc).__name__.lower(),
        message=message,
        failure=failure,
    )


def fail_device_with_error(device: DeviceContext, error: DeviceError) -> DeviceContext:
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, error]}
    )


def abort_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    step_id: str,
    done_ok: dict[str, DeviceContext],
    done_failed: dict[str, DeviceContext],
    message: str,
    failure: FailureInfo | None,
) -> list[StepOutcome]:
    """The remote system was lost after some devices were processed: those keep their result
    (partial effects stay visible), every device not yet processed fails with the transport
    cause."""
    remaining = {
        device_id: mark_device_failed(
            device,
            node_id=node_id,
            step_id=step_id,
            code="remote_system_lost",
            message=message,
            failure=failure,
        )
        for device_id, device in context.devices.items()
        if device_id not in done_ok and device_id not in done_failed
    }
    metadata = {
        **context.metadata,
        f"{node_id}.processed": sorted(done_ok),
        f"{node_id}.aborted": True,
    }
    return [
        StepOutcome(
            name="success",
            summary=f"{len(done_ok)} processed before the connection was lost",
            context=context.model_copy(update={"devices": dict(done_ok), "metadata": metadata}),
        ),
        StepOutcome(
            name="failure",
            summary=message,
            failure=failure,
            context=context.model_copy(
                update={"devices": {**done_failed, **remaining}, "metadata": metadata}
            ),
        ),
    ]
