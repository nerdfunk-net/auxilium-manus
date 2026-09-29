"""Executor for the exists-in-nautobot step."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials
from workflow_steps.common.nautobot_resolve import (
    find_device_id_by_interface_ip,
    find_device_id_by_name,
    find_device_id_by_primary_ip,
)
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.update_field_expression import resolve_update_field_expression
from workflow_steps.exists_in_nautobot.config import get_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "exists-in-nautobot"
_OUTCOME_NAMES = ("exists", "non_existing", "failure")
_STRATEGY_NAME = "name"
_STRATEGY_PRIMARY_IP = "primary_ip"
_STRATEGY_INTERFACE_IP = "interface_ip"
_IP_STRATEGIES = (_STRATEGY_PRIMARY_IP, _STRATEGY_INTERFACE_IP)
_STRATEGIES = (_STRATEGY_NAME, *_IP_STRATEGIES)


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    strategy: str
    ip_expression: str
    case_insensitive: bool


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    defaults = get_config()
    source_id = str(config.get("nautobot_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is not configured")

    strategy = str(config.get("strategy") or defaults["strategy"]).strip()
    if strategy not in _STRATEGIES:
        raise ValueError(
            f"{_STEP_ID}: strategy must be one of {', '.join(_STRATEGIES)} (got {strategy!r})"
        )

    ip_expression = str(config.get("ip_address") or "").strip()
    if strategy in _IP_STRATEGIES and not ip_expression:
        raise ValueError(f"{_STEP_ID}: ip_address is required for strategy {strategy!r}")

    return _ParsedConfig(
        source_id=source_id,
        strategy=strategy,
        ip_expression=ip_expression,
        case_insensitive=bool(config.get("case_insensitive_lookup", False)),
    )


def _bind_nautobot(run: WorkflowRun, source_id: str) -> tuple[NautobotCredentials, NautobotService]:
    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")
    credentials = resolve_nautobot_credentials(db, source_id, step_id=_STEP_ID)
    return credentials, service_factory.get_nautobot_app_service()


def _failed(device: DeviceContext, *, node_id: str, code: str, message: str) -> DeviceContext:
    err = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    return device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )


def _with_nautobot_id(device: DeviceContext, nautobot_id: str) -> DeviceContext:
    bags = {
        **device.attribute_bags,
        "nautobot": {**device.attribute_bags.get("nautobot", {}), "id": nautobot_id},
    }
    return device.model_copy(update={"attribute_bags": bags})


async def _lookup(
    *,
    parsed: _ParsedConfig,
    device: DeviceContext,
    run_id: str,
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
) -> str | None:
    if parsed.strategy == _STRATEGY_NAME:
        if not device.name:
            return None
        return await find_device_id_by_name(
            nautobot_service=nautobot_service,
            credentials=credentials,
            name=device.name,
            case_insensitive=parsed.case_insensitive,
        )

    ip_address = resolve_update_field_expression(
        device=device, field_key="ip_address", raw_value=parsed.ip_expression, run_id=run_id
    )
    if not ip_address:
        raise _IpUnresolvedError(parsed.ip_expression)
    finder = (
        find_device_id_by_primary_ip
        if parsed.strategy == _STRATEGY_PRIMARY_IP
        else find_device_id_by_interface_ip
    )
    return await finder(
        nautobot_service=nautobot_service, credentials=credentials, ip_address=ip_address
    )


class _IpUnresolvedError(Exception):
    def __init__(self, expression: str) -> None:
        super().__init__(f"ip_address expression {expression!r} resolved to nothing")


async def _classify_device(
    *,
    parsed: _ParsedConfig,
    device: DeviceContext,
    node_id: str,
    run_id: str,
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
) -> tuple[str, DeviceContext]:
    try:
        nautobot_id = await _lookup(
            parsed=parsed,
            device=device,
            run_id=run_id,
            nautobot_service=nautobot_service,
            credentials=credentials,
        )
    except _IpUnresolvedError as exc:
        return "failure", _failed(device, node_id=node_id, code="ip_unresolved", message=str(exc))
    except Exception as exc:
        return "failure", _failed(
            device, node_id=node_id, code=type(exc).__name__.lower(), message=str(exc)
        )

    if nautobot_id is None:
        return "non_existing", device
    return "exists", _with_nautobot_id(device, nautobot_id)


def _build_outcomes(
    *,
    context: WorkflowContext,
    node_id: str,
    buckets: dict[str, dict[str, DeviceContext]],
) -> list[StepOutcome]:
    counts = {name: len(buckets[name]) for name in _OUTCOME_NAMES}
    metadata = {**context.metadata, f"{node_id}.exists_counts": counts}
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
        return _build_outcomes(context=context, node_id=node_id, buckets=buckets)

    credentials, nautobot_service = _bind_nautobot(run, parsed.source_id)
    logger.info(
        "exists-in-nautobot started run_id=%s node_id=%s strategy=%s devices=%d",
        context.run_id,
        node_id,
        parsed.strategy,
        len(context.devices),
    )

    results = await asyncio.gather(
        *[
            _classify_device(
                parsed=parsed,
                device=device,
                node_id=node_id,
                run_id=context.run_id,
                nautobot_service=nautobot_service,
                credentials=credentials,
            )
            for device in context.devices.values()
        ]
    )
    for device_id, (bucket, updated) in zip(context.devices, results, strict=True):
        buckets[bucket][device_id] = updated

    logger.info(
        "exists-in-nautobot finished exists=%d non_existing=%d failure=%d run_id=%s",
        len(buckets["exists"]),
        len(buckets["non_existing"]),
        len(buckets["failure"]),
        context.run_id,
    )
    return _build_outcomes(context=context, node_id=node_id, buckets=buckets)
