"""The per-device boundary every device step shares (P-C, D1, W11-01).

A step hands :func:`run_per_device` an async ``work(device_id, device)`` and gets back a
:class:`Batch` of succeeded and failed devices. The work function

* returns the updated ``DeviceContext`` (success),
* returns :class:`Fail` (a device-level failure the step names: not found, rejected, ...), or
* raises. An unexpected exception fails **that device only**: ``device_error_from_exception``
  keeps the text of a ``ValueError`` / ``FileNotFoundError`` (the step wrote it) and reduces
  anything else to the class name plus a ``FailureInfo``, so driver, SQL and secret text never
  reach the stored run.

``concurrency`` is the one knob: ``None`` runs every device at once, ``n`` behind a semaphore,
``1`` one after the other in context order. Only a sequential run may raise :class:`AbortRun`
(the remote system was lost): the run stops, the devices already done stay in the batch and
``Batch.aborted`` carries the cause for ``partial_outcomes.abort_outcomes``.
``asyncio.CancelledError`` is a ``BaseException`` and always passes through.

Not part of it: persisting, logging and building the outcomes (``device_outcomes``), and the
pyATS batch protocol (a chunk of devices per call).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field

from models.failure import FailureInfo
from models.workflow_context import DeviceContext, WorkflowContext, bare_hostname
from workflow_steps.common.device_outcomes import mark_device_failed
from workflow_steps.common.partial_outcomes import (
    device_error_from_exception,
    fail_device_with_error,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Fail:
    """A device-level failure the work function names itself.

    ``device`` is the copy the error is recorded on when the work already changed the device
    (for example it stored a diff artifact before it failed); it defaults to the input device.
    """

    code: str
    message: str
    failure: FailureInfo | None = None
    device: DeviceContext | None = None


class AbortRun(Exception):  # noqa: N818 - a control-flow signal, not an error condition
    """Raised by the work of a sequential run when the remote system is lost."""

    def __init__(self, message: str, failure: FailureInfo | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.failure = failure


@dataclass(frozen=True)
class Batch:
    """The result of one run: devices in context order, plus the abort cause if any."""

    ok: dict[str, DeviceContext] = field(default_factory=dict)
    failed: dict[str, DeviceContext] = field(default_factory=dict)
    aborted: AbortRun | None = None


Work = Callable[[str, DeviceContext], Awaitable[DeviceContext | Fail]]

_ABORT_NEEDS_SEQUENTIAL = "AbortRun is only valid in a sequential run (concurrency=1)"


async def run_per_device(
    context: WorkflowContext,
    work: Work,
    *,
    node_id: str,
    step_id: str,
    concurrency: int | None = None,
    only: Collection[str] | None = None,
    log_label: str | None = None,
) -> Batch:
    """Run ``work`` for the devices of ``context`` (all, or those in ``only``).

    ``log_label`` (a step name) writes one "connecting" and one "ok / failed" line per device,
    with its position, id and host, for the steps whose devices take a while.
    """
    if concurrency is not None and concurrency < 1:
        raise ValueError(f"concurrency must be at least 1, got {concurrency}")
    sequential = concurrency == 1
    devices = [
        (device_id, device)
        for device_id, device in context.devices.items()
        if only is None or device_id in only
    ]

    positions = {device_id: n for n, (device_id, _device) in enumerate(devices, start=1)}

    def _log(device_id: str, device: DeviceContext, state: str) -> None:
        if log_label is None:
            return
        host = bare_hostname(device.primary_ip4, device.hostname) or "(no host)"
        logger.info(
            "%s device %d/%d id=%s host=%s: %s run_id=%s",
            log_label,
            positions[device_id],
            len(devices),
            device_id,
            host,
            state,
            context.run_id,
        )

    async def _one(device_id: str, device: DeviceContext) -> tuple[DeviceContext, bool]:
        _log(device_id, device, "connecting")
        outcome = await _guarded(device_id, device)
        _log(device_id, device, "ok" if outcome[1] else "failed")
        return outcome

    async def _guarded(device_id: str, device: DeviceContext) -> tuple[DeviceContext, bool]:
        try:
            result = await work(device_id, device)
        except AbortRun:
            if not sequential:
                raise RuntimeError(_ABORT_NEEDS_SEQUENTIAL) from None
            raise
        except Exception as exc:
            error = device_error_from_exception(exc, node_id=node_id, step_id=step_id)
            return fail_device_with_error(device, error), False
        if isinstance(result, Fail):
            failed = mark_device_failed(
                result.device or device,
                node_id=node_id,
                step_id=step_id,
                code=result.code,
                message=result.message,
                failure=result.failure,
            )
            return failed, False
        return result, True

    ok: dict[str, DeviceContext] = {}
    failed: dict[str, DeviceContext] = {}

    def _record(device_id: str, outcome: tuple[DeviceContext, bool]) -> None:
        (ok if outcome[1] else failed)[device_id] = outcome[0]

    if sequential:
        for device_id, device in devices:
            try:
                outcome = await _one(device_id, device)
            except AbortRun as stop:
                return Batch(ok=ok, failed=failed, aborted=stop)
            _record(device_id, outcome)
        return Batch(ok=ok, failed=failed)

    gate = asyncio.Semaphore(concurrency) if concurrency else None

    async def _limited(device_id: str, device: DeviceContext) -> tuple[DeviceContext, bool]:
        if gate is None:
            return await _one(device_id, device)
        async with gate:
            return await _one(device_id, device)

    results = await asyncio.gather(*(_limited(i, d) for i, d in devices))
    for (device_id, _device), outcome in zip(devices, results, strict=True):
        _record(device_id, outcome)
    return Batch(ok=ok, failed=failed)
