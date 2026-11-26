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
    StepOutcome,
    WorkflowContext,
)
from services.nautobot.common.exceptions import NautobotError
from workflow_steps.common.device_outcomes import mark_device_failed

# Exception classes whose text is safe to store (D3): the Nautobot client sanitises its messages at
# the source, and the reason Nautobot refused a write is the only thing the operator can act on.
NAUTOBOT_TEXT: tuple[type[BaseException], ...] = (NautobotError,)


def device_error_from_exception(
    exc: BaseException,
    *,
    node_id: str,
    step_id: str,
    keep_text: tuple[type[BaseException], ...] = (),
) -> DeviceError:
    """A closed-vocabulary record plus a message that never contains driver or SQL text.

    ``ValueError`` and ``FileNotFoundError`` messages are written by the steps themselves and are
    safe to keep; any other exception (a database driver, an HTTP client, ...) is reduced to its
    class name, because its text can carry SQL, bound parameters or credentials.

    ``keep_text`` names further classes whose text is safe to store (an integration client that
    sanitises its own messages, for example the Nautobot errors).
    """
    failure = failure_from_exception(exc) or FailureInfo(
        phase="internal", kind="internal_error", exception_type=type(exc).__name__
    )
    message = (
        str(exc)
        if isinstance(exc, (ValueError, FileNotFoundError, *keep_text))
        else type(exc).__name__
    )
    return DeviceError(
        node_id=node_id,
        step_id=step_id,
        code=type(exc).__name__.lower(),
        message=message,
        failure=failure,
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
    extra: dict[str, dict[str, DeviceContext]] | None = None,
) -> list[StepOutcome]:
    """The remote system was lost after some devices were processed: those keep their result
    (partial effects stay visible), every device not yet processed fails with the transport
    cause.

    ``extra`` carries the devices already routed to further handles (``add-to-ise`` answers
    ``exists`` besides ``success`` and ``failure``); each handle keeps its devices.
    """
    extra = extra or {}
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
        if device_id not in done_ok
        and device_id not in done_failed
        and not any(device_id in bucket for bucket in extra.values())
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
        *(
            StepOutcome(
                name=handle,
                summary=f"{len(devices)} processed before the connection was lost",
                context=context.model_copy(update={"devices": dict(devices), "metadata": metadata}),
            )
            for handle, devices in extra.items()
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
