"""Executor for the reachable step."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

from icmplib import ICMPLibError, NameLookupError, async_ping

from core.config import settings
from core.models.runs import WorkflowRun
from core.safe_hosts import validate_inventory_host
from models.failure import FailureInfo
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from services.workflow_context.node_result import set_node_result
from workflow_steps.common.device_outcomes import outcomes_from_buckets
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.step_flags import parse_int_flag
from workflow_steps.reachable.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "reachable"
_OUTCOME_NAMES = ("success", "failure")


# Bounds: a typo must not turn one step into a billion pings or an hour-long wait.
MAX_PING_COUNT = 20
MAX_TIMEOUT_SECONDS = 60.0
# Pings in flight at once: one ICMP socket each, so 2000 devices must not open 2000 sockets.
MAX_CONCURRENT_PINGS = 50


def _parse_positive_int(config: dict[str, Any], key: str) -> int:
    return parse_int_flag(
        config,
        key,
        default=get_config()[key],
        minimum=1,
        maximum=MAX_PING_COUNT,
        step_id=_STEP_ID,
    )


def _parse_positive_number(config: dict[str, Any], key: str) -> float:
    raw = config.get(key, get_config()[key])
    if isinstance(raw, bool):
        raise ValueError(f"{_STEP_ID}: {key} must be a number")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{_STEP_ID}: {key} must be a number") from None
    if not math.isfinite(value) or not 0 < value <= MAX_TIMEOUT_SECONDS:
        raise ValueError(
            f"{_STEP_ID}: {key} must be greater than 0 and at most {MAX_TIMEOUT_SECONDS:g}"
        )
    return value


_MISSING_HOST = FailureInfo(phase="connect", kind="bad_request", hint="check_hostname")
# The host policy refused the address (loopback, link-local / metadata, unspecified, multicast).
_HOST_NOT_ALLOWED = FailureInfo(phase="config", kind="bad_request", hint="check_hostname")
_UNREACHABLE = FailureInfo(phase="connect", kind="timeout", hint="check_reachability")


def _ping_failure(exc: ICMPLibError) -> FailureInfo:
    """A closed record for a library error: a name that did not resolve, else no route."""
    kind = "dns" if isinstance(exc, NameLookupError) else "no_route"
    return FailureInfo(
        phase="connect",
        kind=kind,
        exception_type=type(exc).__name__,
        hint="check_hostname" if kind == "dns" else "check_reachability",
    )


async def _ping_device(
    device: DeviceContext,
    *,
    node_id: str,
    ping_count: int,
    required_replies: int,
    timeout_seconds: float,
) -> DeviceContext | Fail:
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        return Fail("missing_host", "device has no primary_ip4 or hostname to ping", _MISSING_HOST)

    try:
        validate_inventory_host(
            host,
            environment=settings.environment,
            allow_arbitrary=settings.allow_netmiko_arbitrary_hosts,
        )
    except ValueError:
        return Fail("host_not_allowed", "host is not allowed", _HOST_NOT_ALLOWED)

    try:
        result = await async_ping(
            host,
            count=ping_count,
            timeout=timeout_seconds,  # pyright: ignore[reportArgumentType]  # icmplib takes a float
            privileged=False,
        )
    except ICMPLibError as exc:
        # The library text can carry the resolved name or address: class name in the record only.
        return Fail("ping_error", "ping failed", _ping_failure(exc))

    reachable = result.packets_received >= required_replies

    parsed = set_node_result(
        device.parsed,
        node_id,
        "reachability",
        {
            "kind": "reachability_result",
            "reachable": reachable,
            "host": host,
            "packets_sent": result.packets_sent,
            "packets_received": result.packets_received,
            "required_replies": required_replies,
            "avg_rtt_ms": result.avg_rtt,
        },
    )
    enriched = device.model_copy(
        update={
            "parsed": parsed,
            "capabilities": device.capabilities | {Capability.PARSED},
            "status": DeviceStatus.OK if reachable else DeviceStatus.FAILED,
        }
    )
    if reachable:
        return enriched
    return Fail(
        "unreachable",
        f"received {result.packets_received}/{ping_count} replies, required {required_replies}",
        _UNREACHABLE,
        device=enriched,
    )


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del run, artifact_service

    ping_count = _parse_positive_int(config, "ping_count")
    required_replies = _parse_positive_int(config, "required_replies")
    if required_replies > ping_count:
        raise ValueError("reachable: required_replies cannot exceed ping_count")
    timeout_seconds = _parse_positive_number(config, "timeout_seconds")
    if not context.devices:
        return [StepOutcome(name=name, context=context) for name in _OUTCOME_NAMES]

    logger.info(
        "reachable started run_id=%s node_id=%s ping_count=%d required_replies=%d "
        "timeout_seconds=%s",
        context.run_id,
        node_id,
        ping_count,
        required_replies,
        timeout_seconds,
    )

    async def work(_device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return await _ping_device(
            device,
            node_id=node_id,
            ping_count=ping_count,
            required_replies=required_replies,
            timeout_seconds=timeout_seconds,
        )

    batch = await run_per_device(
        context, work, node_id=node_id, step_id=_STEP_ID, concurrency=MAX_CONCURRENT_PINGS
    )
    counts = {"success": len(batch.ok), "failure": len(batch.failed)}
    logger.info("reachable finished run_id=%s counts=%s", context.run_id, counts)
    return outcomes_from_buckets(
        context,
        {"success": batch.ok, "failure": batch.failed},
        metadata={f"{node_id}.reachability_counts": counts},
    )
