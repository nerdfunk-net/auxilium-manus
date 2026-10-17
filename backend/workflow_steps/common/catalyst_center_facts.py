"""Shared driver for steps that read structured facts from Cisco Catalyst Center.

Each fact lands at ``device.parsed[<parsed_output_key>][<fact>] = {"parsed": data | None,
"error": str | None}`` -- the same shape ``run-command`` (TextFSM/Genie) and
``run-catalyst-center-command`` use -- so downstream steps read it one way. A fact that fails
is recorded as an error and does not fail the device; a device fails only when *every*
requested fact failed (typically the controller being unreachable).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel
from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.catalyst_center.common.exceptions import CatalystCenterError
from services.catalyst_center.credentials import CatalystCenterCredentials
from workflow_steps.common.catalyst_center_targets import (
    build_outcomes,
    failed_device,
    resolve_source_credentials,
    split_targets,
)
from workflow_steps.common.jinja_render import JinjaTemplateError, parse_output_key

logger = logging.getLogger(__name__)

# One controller serves every request of a step; keep the load on it modest.
MAX_PARALLEL_DEVICES = 5

Entry = dict[str, Any]
# (credentials, per-source state from ``prepare``, device id, device) -> entries by fact name
CollectFn = Callable[
    [CatalystCenterCredentials, Any, str, DeviceContext], Awaitable[dict[str, Entry]]
]
PrepareFn = Callable[[CatalystCenterCredentials], Awaitable[Any]]


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


# Key an entry carries from ``error_entry`` to ``_with_entries``, which removes it again so the
# persisted ``{parsed, error}`` shape does not change.
_FAILURE_KEY = "failure"


def error_entry(error: FactError | str) -> Entry:
    if isinstance(error, str):
        return {"parsed": None, "error": error}
    return {"parsed": None, "error": error.message, _FAILURE_KEY: error.failure}


async def capture[T](fetch: Callable[[], Awaitable[T]]) -> tuple[T | None, FactError | None]:
    """Run one controller call; a Catalyst Center failure becomes an error message."""
    try:
        return await fetch(), None
    except CatalystCenterError as exc:
        return None, FactError(str(exc), exc.failure)


async def fact(fetch: Callable[[], Awaitable[Any]]) -> Entry:
    value, error = await capture(fetch)
    return error_entry(error) if error is not None else ok_entry(value)


def parse_output_key_config(raw: Any, *, step_id: str, default: str) -> str:
    try:
        return parse_output_key(raw or default)
    except JinjaTemplateError as exc:
        raise ValueError(f"{step_id}: parsed_output_key: {exc}") from exc


def _with_entries(
    device: DeviceContext,
    entries: dict[str, Entry],
    *,
    output_key: str,
    step_id: str,
    node_id: str,
) -> tuple[DeviceContext, bool]:
    clean = {
        name: {k: v for k, v in entry.items() if k != _FAILURE_KEY}
        for name, entry in entries.items()
    }
    parsed = {**device.parsed, output_key: clean}
    errors = {name: entry["error"] for name, entry in entries.items() if entry["error"]}
    if entries and len(errors) == len(entries):
        message = "; ".join(f"{name}: {error}" for name, error in errors.items())
        failure = next(
            (f for name in errors if (f := entries[name].get(_FAILURE_KEY)) is not None), None
        )
        return (
            failed_device(
                device,
                step_id=step_id,
                node_id=node_id,
                code="catalyst_center_error",
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


async def run_fact_step(
    *,
    step_id: str,
    context: WorkflowContext,
    run: WorkflowRun,
    node_id: str,
    output_key: str,
    collect: CollectFn,
    prepare: PrepareFn | None = None,
) -> list[StepOutcome]:
    """Resolve targets/credentials, collect facts per device, and build the outcomes."""
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{step_id}: WorkflowRun has no active DB session")

    split = split_targets(context.devices, step_id=step_id, node_id=node_id)
    credentials = resolve_source_credentials(db, list(split.by_source), step_id=step_id)

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d",
        step_id,
        context.run_id,
        node_id,
        len(context.devices),
    )

    # ``prepare`` runs once per controller (for example a controller-wide topology fetch).
    source_ids = list(split.by_source)
    states = (
        await asyncio.gather(*[prepare(credentials[source_id]) for source_id in source_ids])
        if prepare is not None
        else [None] * len(source_ids)
    )
    state_by_source = dict(zip(source_ids, states, strict=True))

    gate = asyncio.Semaphore(MAX_PARALLEL_DEVICES)

    async def one(
        source_id: str, device_id: str, device: DeviceContext
    ) -> tuple[str, DeviceContext, bool]:
        async with gate:
            entries = await collect(
                credentials[source_id], state_by_source[source_id], device_id, device
            )
        updated, ok = _with_entries(
            device, entries, output_key=output_key, step_id=step_id, node_id=node_id
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
