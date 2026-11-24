"""Executor for the get-device-location step."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    DeviceContext,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials
from services.workflow_context.attribute_path import DEVICE_SCALAR_FIELDS
from workflow_steps.common.attribute_write import RESERVED_BAG_NAMES, set_device_attribute
from workflow_steps.common.device_outcomes import build_outcomes
from workflow_steps.common.device_runner import Fail, run_per_device
from workflow_steps.common.nautobot_resolve import resolve_nautobot_device_id
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.step_flags import parse_bool_flag
from workflow_steps.get_device_location.chain import (
    LOCATION_CHAIN_QUERY,
    describe_chain,
    find_locations_by_type,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-device-location"
_DEFAULT_TARGET = "custom.location"


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    location_type: str
    target_attribute: str
    case_insensitive_lookup: bool


def _validate_target(target: str) -> str:
    bag, _, field = target.partition(".")
    if not bag or not field or any(not part for part in target.split(".")):
        raise ValueError(
            f"{_STEP_ID}: target_attribute must be in bag.field form (for example custom.location)"
        )
    if bag == "device" or bag in RESERVED_BAG_NAMES or bag in DEVICE_SCALAR_FIELDS:
        raise ValueError(f"{_STEP_ID}: target_attribute cannot write to the {bag!r} namespace")
    return target


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    source_id = str(config.get("nautobot_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is not configured")
    location_type = str(config.get("location_type") or "").strip()
    if not location_type:
        raise ValueError(f"{_STEP_ID}: location_type is not configured")
    target = str(config.get("target_attribute") or _DEFAULT_TARGET).strip()
    return _ParsedConfig(
        source_id=source_id,
        location_type=location_type,
        target_attribute=_validate_target(target),
        case_insensitive_lookup=parse_bool_flag(config, "case_insensitive_lookup", default=False),
    )


def _bind_nautobot(
    run: WorkflowRun, source_id: str
) -> tuple[NautobotCredentials, NautobotService]:
    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")
    credentials = resolve_nautobot_credentials(db, source_id, step_id=_STEP_ID)
    return credentials, service_factory.get_nautobot_app_service()


def _located_failure(
    code: str,
    message: str,
    kind: Literal["not_found", "ambiguous_match"] = "not_found",
) -> Fail:
    return Fail(code, message, FailureInfo(phase="api", kind=kind))


async def _locate_device(
    *,
    device: DeviceContext,
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
    parsed: _ParsedConfig,
) -> DeviceContext | Fail:
    """The device with its location written, or the failure of a lookup that found nothing.

    An unexpected error is turned into a failed device by the runner (class name only).
    """
    nautobot_id = await resolve_nautobot_device_id(
        nautobot_service=nautobot_service,
        credentials=credentials,
        device=device,
        case_insensitive=parsed.case_insensitive_lookup,
    )
    if nautobot_id is None:
        return _located_failure(
            "not_found",
            f"No Nautobot device found for workflow device {device.id} "
            f"(name={device.name!r}, ip={device.primary_ip4!r})",
        )
    response = await nautobot_service.graphql_query(
        LOCATION_CHAIN_QUERY, {"deviceId": nautobot_id}, credentials, strict=True
    )
    nautobot_device = (response.get("data") or {}).get("device")
    if nautobot_device is None:
        return _located_failure("not_found", f"No Nautobot data returned for device {device.id}")
    location = nautobot_device.get("location")
    names = find_locations_by_type(location, parsed.location_type)
    if len(names) > 1:
        return _located_failure(
            "location_type_ambiguous",
            f"Location type {parsed.location_type!r} occurs {len(names)} times in the "
            f"hierarchy ({', '.join(names)}); it is a nestable type: {describe_chain(location)}",
            "ambiguous_match",
        )
    if not names:
        return _located_failure(
            "location_type_not_found",
            f"No location of type {parsed.location_type!r} in the hierarchy: "
            f"{describe_chain(location)}",
        )
    return set_device_attribute(device, parsed.target_attribute, names[0])


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

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    parsed = _parse_config(config)
    credentials, nautobot_service = _bind_nautobot(run, parsed.source_id)

    logger.info(
        "get-device-location started run_id=%s source_id=%s location_type=%s target=%s devices=%d",
        log_run_id(run),
        parsed.source_id,
        parsed.location_type,
        parsed.target_attribute,
        len(context.devices),
    )

    async def work(_device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        return await _locate_device(
            device=device,
            nautobot_service=nautobot_service,
            credentials=credentials,
            parsed=parsed,
        )

    batch = await run_per_device(context, work, node_id=node_id, step_id=_STEP_ID)
    logger.info(
        "get-device-location finished success=%d failure=%d run_id=%s",
        len(batch.ok),
        len(batch.failed),
        log_run_id(run),
    )
    return build_outcomes(context, batch.ok, batch.failed)
