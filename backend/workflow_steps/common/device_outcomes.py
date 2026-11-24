"""Source-agnostic helpers for steps that act on devices of one external source.

The one outcome API (P-B, W1-01): failing a device with a structured
:class:`~models.workflow_context.DeviceError` (``mark_device_failed``), splitting per-device results
(``DeviceResult``, ``partition_results``) and building the ``success`` / ``failure`` outcomes
(``build_outcomes``, ``outcomes_from_buckets``, ``whole_step_failure``). Also groups devices by
``source_id`` for the controller-backed steps (Cisco Catalyst Center, Cisco ACI).

Additive: the private copies in the step packages migrate here family by family (P-C), and
``tests/unit/test_private_outcome_helpers_ratchet.py`` lets their number only fall.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NamedTuple

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


def mark_device_failed(
    device: DeviceContext,
    *,
    node_id: str,
    step_id: str,
    code: str,
    message: str,
    failure: FailureInfo | None = None,
    **updates: Any,
) -> DeviceContext:
    """A copy of ``device`` marked FAILED with one more ``DeviceError``.

    ``updates`` are further fields of the copy (for example ``command_results``); the error
    history of ``device`` is kept and the input is never mutated.
    """
    error = DeviceError(
        node_id=node_id, step_id=step_id, code=code, message=message, failure=failure
    )
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, error], **updates}
    )


# The older name of the same function; the controller steps still import it (P-X4 removes it).
failed_device = mark_device_failed


class DeviceResult(NamedTuple):
    """What a per-device worker returns. A plain ``(id, device, ok)`` tuple works as well."""

    device_id: str
    device: DeviceContext
    ok: bool


def partition_results(
    results: Iterable[tuple[str, DeviceContext, bool]],
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext]]:
    """Split ``(id, device, ok)`` results into the succeeded and the failed devices."""
    succeeded: dict[str, DeviceContext] = {}
    failed: dict[str, DeviceContext] = {}
    for device_id, device, ok in results:
        (succeeded if ok else failed)[device_id] = device
    return succeeded, failed


def build_outcomes(
    context: WorkflowContext,
    succeeded: dict[str, DeviceContext],
    failed: dict[str, DeviceContext],
    *,
    metadata: Mapping[str, Any] | None = None,
    success_summary: str | None = None,
    failure_summary: str | None = None,
) -> list[StepOutcome]:
    """``success`` always, ``failure`` only when a device failed.

    ``metadata`` is merged over the context's metadata (the input context is not changed).
    """
    merged = {**context.metadata, **(metadata or {})}
    outcomes = [
        StepOutcome(
            name="success",
            summary=success_summary,
            context=context.model_copy(update={"devices": succeeded, "metadata": merged}),
        )
    ]
    if failed:
        outcomes.append(
            StepOutcome(
                name="failure",
                summary=failure_summary,
                context=context.model_copy(update={"devices": failed, "metadata": merged}),
            )
        )
    return outcomes


def outcomes_from_buckets(
    context: WorkflowContext,
    buckets: Mapping[str, Mapping[str, DeviceContext]],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> list[StepOutcome]:
    """One outcome per bucket, in the order of ``buckets``, empty ones included.

    The router variant (``success`` and ``failure`` both always present, or ``clean`` / ``dirty``
    / ``failure`` ...): a downstream edge on an empty handle then sees an empty device set
    instead of a missing outcome.
    """
    merged = {**context.metadata, **(metadata or {})}
    return [
        StepOutcome(
            name=name,
            context=context.model_copy(update={"devices": dict(devices), "metadata": merged}),
        )
        for name, devices in buckets.items()
    ]


def whole_step_failure(
    context: WorkflowContext,
    *,
    node_id: str,
    step_id: str,
    code: str,
    message: str,
    failure: FailureInfo | None = None,
    metadata: Mapping[str, Any] | None = None,
    empty_handles: Sequence[str] = ("success",),
) -> list[StepOutcome]:
    """The step as a whole failed: every device is FAILED with the same error.

    ``empty_handles`` are emitted empty before ``failure`` (a routing step lists its verdict
    handles so a failed check never reads as a verdict). The ``failure`` outcome carries
    ``failure`` and ``message`` as its summary.
    """
    merged = {**context.metadata, **(metadata or {})}
    failed = {
        device_id: mark_device_failed(
            device, node_id=node_id, step_id=step_id, code=code, message=message, failure=failure
        )
        for device_id, device in context.devices.items()
    }
    return [
        *(
            StepOutcome(
                name=name,
                context=context.model_copy(update={"devices": {}, "metadata": merged}),
            )
            for name in empty_handles
        ),
        StepOutcome(
            name="failure",
            summary=message,
            failure=failure,
            context=context.model_copy(update={"devices": failed, "metadata": merged}),
        ),
    ]
