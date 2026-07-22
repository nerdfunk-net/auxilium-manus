"""Executor for the reachable step."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from icmplib import ICMPLibError, async_ping

from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from workflow_steps.reachable.config import get_config

logger = logging.getLogger(__name__)

_OUTCOME_NAMES = ("success", "failure")


def _default_config() -> dict[str, Any]:
    return get_config()


def _parse_positive_int(config: dict[str, Any], key: str) -> int:
    raw = config.get(key, _default_config()[key])
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError(f"reachable: {key} must be a whole number") from None
    if value < 1:
        raise ValueError(f"reachable: {key} must be at least 1")
    return value


def _parse_positive_number(config: dict[str, Any], key: str) -> float:
    raw = config.get(key, _default_config()[key])
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"reachable: {key} must be a number") from None
    if value <= 0:
        raise ValueError(f"reachable: {key} must be greater than 0")
    return value


def _device_failure(
    device: DeviceContext, *, node_id: str, code: str, message: str
) -> DeviceContext:
    err = DeviceError(node_id=node_id, step_id="reachable", code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )


async def _ping_device(
    device: DeviceContext,
    *,
    node_id: str,
    ping_count: int,
    required_replies: int,
    timeout_seconds: float,
) -> tuple[str, DeviceContext]:
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        return "failure", _device_failure(
            device,
            node_id=node_id,
            code="missing_host",
            message="device has no primary_ip4 or hostname to ping",
        )

    try:
        result = await async_ping(
            host,
            count=ping_count,
            timeout=timeout_seconds,
            privileged=False,
        )
    except ICMPLibError as exc:
        return "failure", _device_failure(
            device, node_id=node_id, code="ping_error", message=str(exc)
        )

    reachable = result.packets_received >= required_replies

    parsed = dict(device.parsed)
    parsed[f"{node_id}.reachability"] = {
        "kind": "reachability_result",
        "reachable": reachable,
        "host": host,
        "packets_sent": result.packets_sent,
        "packets_received": result.packets_received,
        "required_replies": required_replies,
        "avg_rtt_ms": result.avg_rtt,
    }
    enriched = device.model_copy(
        update={
            "parsed": parsed,
            "capabilities": device.capabilities | {Capability.PARSED},
            "status": DeviceStatus.OK if reachable else DeviceStatus.FAILED,
        }
    )

    if reachable:
        return "success", enriched

    failed = enriched.model_copy(
        update={
            "errors": [
                *enriched.errors,
                DeviceError(
                    node_id=node_id,
                    step_id="reachable",
                    code="unreachable",
                    message=(
                        f"received {result.packets_received}/{ping_count} replies, "
                        f"required {required_replies}"
                    ),
                ),
            ]
        }
    )
    return "failure", failed


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del run, artifact_service

    if not context.devices:
        return [StepOutcome(name=name, context=context) for name in _OUTCOME_NAMES]

    ping_count = _parse_positive_int(config, "ping_count")
    required_replies = _parse_positive_int(config, "required_replies")
    if required_replies > ping_count:
        raise ValueError("reachable: required_replies cannot exceed ping_count")
    timeout_seconds = _parse_positive_number(config, "timeout_seconds")

    logger.info(
        "reachable started run_id=%s node_id=%s ping_count=%d required_replies=%d "
        "timeout_seconds=%s",
        context.run_id,
        node_id,
        ping_count,
        required_replies,
        timeout_seconds,
    )

    results = await asyncio.gather(
        *(
            _ping_device(
                device,
                node_id=node_id,
                ping_count=ping_count,
                required_replies=required_replies,
                timeout_seconds=timeout_seconds,
            )
            for device in context.devices.values()
        )
    )

    buckets: dict[str, dict[str, DeviceContext]] = {"success": {}, "failure": {}}
    for device_id, (outcome_name, device) in zip(
        context.devices.keys(), results, strict=True
    ):
        buckets[outcome_name][device_id] = device

    counts = {name: len(buckets[name]) for name in _OUTCOME_NAMES}
    metadata = {**context.metadata, f"{node_id}.reachability_counts": counts}

    logger.info(
        "reachable finished run_id=%s counts=%s",
        context.run_id,
        counts,
    )

    return [
        StepOutcome(
            name=name,
            context=context.model_copy(
                update={"devices": dict(buckets[name]), "metadata": metadata}
            ),
        )
        for name in _OUTCOME_NAMES
    ]
