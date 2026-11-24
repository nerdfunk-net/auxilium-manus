"""Source-agnostic core of the steps that read structured facts from a controller.

Each fact lands at ``device.parsed[<parsed_output_key>][<fact>] = {"parsed": data | None,
"error": str | None}`` -- the same shape ``run-command`` (TextFSM/Genie) uses -- so downstream steps
read it one way. A fact that fails is recorded as an error and does not fail the device; a device
fails only when *every* requested fact failed (typically the controller being unreachable).

The per-source parts (which exception is a controller failure, how targets are split, how
credentials resolve) live in ``catalyst_center_facts.py`` and ``aci_facts.py``.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from models.failure import FailureInfo
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from workflow_steps.common.device_outcomes import TargetSplit, build_outcomes, failed_device
from workflow_steps.common.jinja_render import JinjaTemplateError, parse_output_key
from workflow_steps.common.partial_outcomes import (
    device_error_from_exception,
    fail_device_with_error,
)

logger = logging.getLogger(__name__)

# One controller serves every request of a step; keep the load on it modest.
MAX_PARALLEL_DEVICES = 5

Entry = dict[str, Any]


def dump(value: Any) -> Any:
    """JSON-ready form of a normalized model (or a sequence of them)."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, (list, tuple)):
        return [dump(item) for item in value]
    return value


def ok_entry(value: Any) -> Entry:
    return {"parsed": dump(value), "error": None}


@dataclass(frozen=True)
class FactError:
    """A failed controller call: the readable message plus its structured cause."""

    message: str
    failure: FailureInfo | None = None


# Key an entry carries from ``error_entry`` to ``with_entries``, which removes it again so the
# persisted ``{parsed, error}`` shape does not change.
FAILURE_KEY = "failure"


def error_entry(error: FactError | str) -> Entry:
    if isinstance(error, str):
        return {"parsed": None, "error": error}
    return {"parsed": None, "error": error.message, FAILURE_KEY: error.failure}


def parse_output_key_config(
    raw: Any, *, step_id: str, default: str, key_name: str = "parsed_output_key"
) -> str:
    try:
        return parse_output_key(raw or default)
    except JinjaTemplateError as exc:
        raise ValueError(f"{step_id}: {key_name}: {exc}") from exc


def with_entries(
    device: DeviceContext,
    entries: dict[str, Entry],
    *,
    output_key: str,
    step_id: str,
    node_id: str,
    error_code: str,
) -> tuple[DeviceContext, bool]:
    """Store ``entries`` on the device; the device fails only if every entry is an error."""
    clean = {
        name: {k: v for k, v in entry.items() if k != FAILURE_KEY}
        for name, entry in entries.items()
    }
    parsed = {**device.parsed, output_key: clean}
    errors = {name: entry["error"] for name, entry in entries.items() if entry["error"]}
    if entries and len(errors) == len(entries):
        message = "; ".join(f"{name}: {error}" for name, error in errors.items())
        failure = next(
            (f for name in errors if (f := entries[name].get(FAILURE_KEY)) is not None), None
        )
        return (
            failed_device(
                device,
                step_id=step_id,
                node_id=node_id,
                code=error_code,
                message=message,
                failure=failure,
                parsed=parsed,
            ),
            False,
        )
    return (
        device.model_copy(
            update={
                "status": DeviceStatus.OK,
                "parsed": parsed,
                "capabilities": device.capabilities | {Capability.PARSED},
            }
        ),
        True,
    )


async def _prepare_source[CredsT](
    prepare: Callable[[CredsT], Awaitable[Any]] | None, credentials: CredsT
) -> tuple[Any, Exception | None]:
    """``(state, None)``, or ``(None, the exception)`` when ``prepare`` raised."""
    if prepare is None:
        return None, None
    try:
        return await prepare(credentials), None
    except Exception as exc:
        return None, exc


async def collect_facts[CredsT](
    *,
    step_id: str,
    context: WorkflowContext,
    node_id: str,
    output_key: str,
    collect: Callable[[CredsT, Any, str, DeviceContext], Awaitable[dict[str, Entry]]],
    split: TargetSplit,
    credentials: Mapping[str, CredsT],
    error_code: str,
    prepare: Callable[[CredsT], Awaitable[Any]] | None = None,
) -> list[StepOutcome]:
    """Collect facts per device (bounded parallelism) and build the success/failure outcomes."""
    logger.info(
        "%s started run_id=%s node_id=%s devices=%d",
        step_id,
        context.run_id,
        node_id,
        len(context.devices),
    )

    # ``prepare`` runs once per controller (for example a controller-wide topology fetch). A
    # controller error is turned into state by the step itself; anything else it raises (a bug,
    # a service that cannot be built) fails the devices of that controller only, the other
    # controllers go on. Cancellation always passes through.
    source_ids = list(split.by_source)
    prepared = await asyncio.gather(
        *[_prepare_source(prepare, credentials[source_id]) for source_id in source_ids]
    )
    state_by_source = {
        source_id: state
        for source_id, (state, raised) in zip(source_ids, prepared, strict=True)
        if raised is None
    }
    prepare_errors = {
        source_id: device_error_from_exception(raised, node_id=node_id, step_id=step_id)
        for source_id, (_state, raised) in zip(source_ids, prepared, strict=True)
        if raised is not None
    }

    gate = asyncio.Semaphore(MAX_PARALLEL_DEVICES)

    async def one(
        source_id: str, device_id: str, device: DeviceContext
    ) -> tuple[str, DeviceContext, bool]:
        if source_id in prepare_errors:
            return device_id, fail_device_with_error(device, prepare_errors[source_id]), False
        async with gate:
            try:
                entries = await collect(
                    credentials[source_id], state_by_source[source_id], device_id, device
                )
            except Exception as exc:
                # A controller error is turned into an entry by each step's ``fact()``; anything
                # else (a bug, a parsing error) fails this device only (W8-01).
                error = device_error_from_exception(exc, node_id=node_id, step_id=step_id)
                return device_id, fail_device_with_error(device, error), False
        updated, ok = with_entries(
            device,
            entries,
            output_key=output_key,
            step_id=step_id,
            node_id=node_id,
            error_code=error_code,
        )
        return device_id, updated, ok

    results = await asyncio.gather(
        *[
            one(source_id, device_id, device)
            for source_id, devices in split.by_source.items()
            for device_id, device in devices.items()
        ]
    )

    succeeded: dict[str, DeviceContext] = {}
    failed: dict[str, DeviceContext] = dict(split.rejected)
    for device_id, device, ok in results:
        (succeeded if ok else failed)[device_id] = device

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        step_id,
        len(succeeded),
        len(failed),
        context.run_id,
    )
    return build_outcomes(context, succeeded, failed)
