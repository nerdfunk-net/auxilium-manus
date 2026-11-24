"""Shared driver for steps that read structured facts from Cisco Catalyst Center.

Each fact lands at ``device.parsed[<parsed_output_key>][<fact>] = {"parsed": data | None,
"error": str | None}``. The entry shape, the per-device collection loop and the "a device fails
only when every fact failed" rule are source-agnostic and live in ``fact_entries``; this module
adds what is specific to Catalyst Center: which exception is a controller failure, how targets
are split (devices must come from a Catalyst Center source) and how credentials resolve.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.catalyst_center.common.exceptions import CatalystCenterError
from services.catalyst_center.credentials import CatalystCenterCredentials
from workflow_steps.common.catalyst_center_targets import (
    resolve_source_credentials,
    split_targets,
)
from workflow_steps.common.fact_entries import (
    Entry,
    FactError,
    collect_facts,
    error_entry,
    ok_entry,
    parse_output_key_config,
)
from workflow_steps.common.run_session import require_session

__all__ = [
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

CATALYST_ERROR_CODE = "catalyst_center_error"

# (credentials, per-source state from ``prepare``, device id, device) -> entries by fact name
CollectFn = Callable[
    [CatalystCenterCredentials, Any, str, DeviceContext], Awaitable[dict[str, Entry]]
]
PrepareFn = Callable[[CatalystCenterCredentials], Awaitable[Any]]


async def capture[T](fetch: Callable[[], Awaitable[T]]) -> tuple[T | None, FactError | None]:
    """Run one controller call; a Catalyst Center failure becomes an error message."""
    try:
        return await fetch(), None
    except CatalystCenterError as exc:
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
    prepare: PrepareFn | None = None,
) -> list[StepOutcome]:
    """Resolve targets/credentials, collect facts per device, and build the outcomes."""
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = require_session(run, step_id)

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
        error_code=CATALYST_ERROR_CODE,
        prepare=prepare,
    )
