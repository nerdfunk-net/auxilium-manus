"""Shared driver for steps that read structured facts from Cisco ACI switches.

The entry shape, the per-device collection loop and the "a device fails only when every fact
failed" rule are source-agnostic and live in ``fact_entries``; this module adds what is specific to
ACI: which exception is an APIC failure, how targets are split and how credentials resolve.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.orm import object_session

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.aci.common.exceptions import AciError
from services.aci.credentials import AciCredentials
from workflow_steps.common.aci_targets import resolve_source_credentials, split_targets
from workflow_steps.common.fact_entries import (
    Entry,
    FactError,
    collect_facts,
    error_entry,
    ok_entry,
    parse_output_key_config,
)

__all__ = [
    "ACI_ERROR_CODE",
    "CollectFn",
    "Entry",
    "FactError",
    "capture",
    "error_entry",
    "fact",
    "ok_entry",
    "parse_output_key_config",
    "run_fact_step",
]

ACI_ERROR_CODE = "aci_error"

# (credentials, per-source state, device id, device) -> entries by fact name
CollectFn = Callable[[AciCredentials, Any, str, DeviceContext], Awaitable[dict[str, Entry]]]


async def capture[T](fetch: Callable[[], Awaitable[T]]) -> tuple[T | None, FactError | None]:
    """Run one APIC read; an ACI failure becomes an error message with its structured cause."""
    try:
        return await fetch(), None
    except AciError as exc:
        return None, FactError(str(exc), exc.failure)


async def fact(fetch: Callable[[], Awaitable[Any]]) -> Entry:
    value, error = await capture(fetch)
    return error_entry(error) if error is not None else ok_entry(value)


async def run_fact_step(
    *,
    step_id: str,
    context: WorkflowContext,
    run: WorkflowRun,
    node_id: str,
    output_key: str,
    collect: CollectFn,
) -> list[StepOutcome]:
    """Resolve targets/credentials, collect facts per device, and build the outcomes."""
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{step_id}: WorkflowRun has no active DB session")

    split = split_targets(context.devices, step_id=step_id, node_id=node_id)
    credentials = resolve_source_credentials(db, list(split.by_source), step_id=step_id)
    return await collect_facts(
        step_id=step_id,
        context=context,
        node_id=node_id,
        output_key=output_key,
        collect=collect,
        split=split,
        credentials=credentials,
        error_code=ACI_ERROR_CODE,
    )
