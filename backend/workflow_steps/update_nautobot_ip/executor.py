"""Executor for the update-nautobot-ip step.

All Nautobot work is done by the shared ``DeviceCommonService`` (IPManager): the step resolves the
IP address id and the new values per device, looks up namespace, status and role once per distinct
value, and reports per device. An empty field is left unchanged.

With ``ips_from_interfaces`` the step instead updates every IP address on the device's interfaces
with the configured values (``interfaces_mode.py``).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.nautobot.common.validators import is_valid_uuid
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.devices.common import DeviceCommonService
from workflow_steps.common.device_outcomes import fail_device_with_error
from workflow_steps.common.nautobot_plan_fields import (
    PlanError,
    bad_request_failure,
    resolve_fields,
)
from workflow_steps.common.nautobot_step import NAUTOBOT_CONCURRENCY, bind_nautobot_client
from workflow_steps.common.step_flags import parse_bool_flag
from workflow_steps.update_nautobot_ip.interfaces_mode import run_from_interfaces
from workflow_steps.update_nautobot_ip.lookups import (
    FIELDS,
    STEP_ID,
    Plan,
    failed,
    lookup_error,
    parent_finder,
    resolve_ids,
    split_values,
    write_error,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_OUTCOME_NAMES = ("success", "failure")
_IP_VERSIONS = ("", "4", "6")


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    ip_id_expression: str
    expressions: dict[str, str]
    from_interfaces: bool = False
    ip_version: str = ""
    dry_run: bool = False


@dataclass(frozen=True)
class _Bound:
    common: DeviceCommonService
    client: CredentialsBoundNautobotClient


def _text(config: dict[str, Any], key: str) -> str:
    return str(config.get(key) or "").strip()


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    source_id = _text(config, "nautobot_source_id")
    if not source_id:
        raise ValueError(f"{STEP_ID}: nautobot_source_id is not configured")
    ip_id_expression = _text(config, "ip_id")
    from_interfaces = parse_bool_flag(config, "ips_from_interfaces")
    if from_interfaces and ip_id_expression:
        raise ValueError(
            f"{STEP_ID}: ips_from_interfaces updates the addresses of the interfaces; clear ip_id"
        )
    if not from_interfaces and not ip_id_expression:
        raise ValueError(f"{STEP_ID}: ip_id is not configured")
    dry_run = parse_bool_flag(config, "dry_run")
    if dry_run and not from_interfaces:
        # Only the interfaces mode previews; ignoring the flag here would write to Nautobot.
        raise ValueError(
            f"{STEP_ID}: dry_run only works with ips_from_interfaces; "
            "switch it off or the step would write"
        )
    ip_version = _text(config, "ip_version")
    if ip_version not in _IP_VERSIONS:
        raise ValueError(f"{STEP_ID}: ip_version must be empty, 4 or 6")
    expressions = {field: _text(config, field) for field in FIELDS}
    if not any(expressions.values()):
        raise ValueError(f"{STEP_ID}: configure at least one field to update ({', '.join(FIELDS)})")
    return _ParsedConfig(
        source_id,
        ip_id_expression,
        expressions,
        from_interfaces=from_interfaces,
        ip_version=ip_version,
        dry_run=dry_run,
    )


def _bind_nautobot(run: WorkflowRun, source_id: str) -> _Bound:
    client = bind_nautobot_client(run, source_id, step_id=STEP_ID)
    return _Bound(DeviceCommonService(client), client)


def _plan_device(parsed: _ParsedConfig, device: DeviceContext, run_id: str) -> Plan | PlanError:
    """A ``Plan``, or ``(code, message, failure)`` when the device cannot be updated."""
    resolved = resolve_fields(
        device, run_id, (("ip_id", parsed.ip_id_expression), *parsed.expressions.items())
    )
    if isinstance(resolved, tuple):
        return resolved
    # The value is not echoed: it can come from an attribute and ends up in the stored error.
    ip_id = resolved.pop("ip_id", "")
    if not is_valid_uuid(ip_id.lower()):
        return "ip_id_invalid", "ip_id is not a Nautobot UUID", bad_request_failure()
    split = split_values(resolved)
    if isinstance(split, tuple):
        return split
    return Plan(device=device, ip_id=ip_id, values=split.values, namespace=split.namespace)


async def _update(bound: _Bound, plan: Plan, node_id: str) -> tuple[str, DeviceContext, bool]:
    device = plan.device
    find_parent = parent_finder(bound.client, plan.namespace) if plan.namespace else None
    try:
        changed = await bound.common.update_ip_address(
            plan.ip_id, plan.values, find_parent=find_parent
        )
    except Exception as exc:
        return "failure", fail_device_with_error(device, write_error(exc, node_id)), False
    return "success", device, changed


def _build_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    buckets: dict[str, dict[str, DeviceContext]],
    updated: int,
) -> list[StepOutcome]:
    counts = {
        "updated": updated,
        "unchanged": len(buckets["success"]) - updated,
        "failed": len(buckets["failure"]),
    }
    metadata = {**context.metadata, f"{node_id}.update_ip_counts": counts}
    return [
        StepOutcome(
            name=name,
            context=context.model_copy(
                update={"devices": dict(buckets[name]), "metadata": metadata}
            ),
        )
        for name in _OUTCOME_NAMES
    ]


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions

    parsed = _parse_config(config)
    buckets: dict[str, dict[str, DeviceContext]] = {name: {} for name in _OUTCOME_NAMES}
    if not context.devices:
        return _build_outcomes(context=context, node_id=node_id, buckets=buckets, updated=0)

    bound = _bind_nautobot(run, parsed.source_id)
    if parsed.from_interfaces:
        return await run_from_interfaces(
            common=bound.common,
            client=bound.client,
            context=context,
            node_id=node_id,
            expressions=parsed.expressions,
            ip_version=parsed.ip_version,
            dry_run=parsed.dry_run,
        )
    common = bound.common
    logger.info(
        "update-nautobot-ip started run_id=%s node_id=%s devices=%d",
        context.run_id,
        node_id,
        len(context.devices),
    )

    results: dict[str, tuple[str, DeviceContext]] = {}
    ready: list[Plan] = []
    cache: dict[tuple[str, str], str | Exception] = {}
    for device in context.devices.values():
        planned = _plan_device(parsed, device, context.run_id)
        if isinstance(planned, tuple):
            code, message, failure = planned
            results[device.id] = (
                "failure",
                failed(device, node_id=node_id, code=code, message=message, failure=failure),
            )
            continue
        # Resolved one device after another so a shared name is looked up exactly once.
        resolved = await resolve_ids(common, planned, cache)
        if isinstance(resolved, tuple):
            code, exc = resolved
            results[device.id] = ("failure", lookup_error(code, exc, node_id, device))
        else:
            ready.append(resolved)

    gate = asyncio.Semaphore(NAUTOBOT_CONCURRENCY)

    async def run_one(plan: Plan) -> tuple[str, DeviceContext, bool]:
        async with gate:
            return await _update(bound, plan, node_id)

    done = await asyncio.gather(*[run_one(plan) for plan in ready])
    updated = 0
    for plan, (bucket, device, changed) in zip(ready, done, strict=True):
        results[plan.device.id] = (bucket, device)
        updated += int(changed)

    for device_id in context.devices:
        bucket, device = results[device_id]
        buckets[bucket][device_id] = device

    logger.info(
        "update-nautobot-ip finished success=%d failure=%d updated=%d run_id=%s",
        len(buckets["success"]),
        len(buckets["failure"]),
        updated,
        context.run_id,
    )
    return _build_outcomes(context=context, node_id=node_id, buckets=buckets, updated=updated)
