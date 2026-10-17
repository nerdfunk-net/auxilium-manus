"""Executor for the get-device-location step."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials
from services.workflow_context.attribute_path import DEVICE_SCALAR_FIELDS
from workflow_steps.common.attribute_write import RESERVED_BAG_NAMES, set_device_attribute
from workflow_steps.common.nautobot_resolve import resolve_nautobot_device_id
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.partial_outcomes import (
    device_error_from_exception,
    fail_device_with_error,
)
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


def _failed(
    device: DeviceContext,
    node_id: str,
    code: str,
    message: str,
    kind: Literal["not_found", "ambiguous_match"] = "not_found",
) -> DeviceContext:
    error = DeviceError(
        node_id=node_id,
        step_id=_STEP_ID,
        code=code,
        message=message,
        failure=FailureInfo(phase="api", kind=kind),
    )
    return fail_device_with_error(device, error)


async def _locate_device(
    *,
    device: DeviceContext,
    node_id: str,
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
    parsed: _ParsedConfig,
) -> tuple[DeviceContext, bool]:
    """Return ``(device, ok)``; a failed lookup returns the device with an error attached."""
    nautobot_id = await resolve_nautobot_device_id(
        nautobot_service=nautobot_service,
        credentials=credentials,
        device=device,
        case_insensitive=parsed.case_insensitive_lookup,
    )
    if nautobot_id is None:
        return _failed(
            device, node_id, "not_found",
            f"No Nautobot device found for workflow device {device.id} "
            f"(name={device.name!r}, ip={device.primary_ip4!r})",
        ), False
    response = await nautobot_service.graphql_query(
        LOCATION_CHAIN_QUERY, {"deviceId": nautobot_id}, credentials, strict=True
    )
    nautobot_device = (response.get("data") or {}).get("device")
    if nautobot_device is None:
        return _failed(
            device, node_id, "not_found",
            f"No Nautobot data returned for device {device.id}",
        ), False
    location = nautobot_device.get("location")
    names = find_locations_by_type(location, parsed.location_type)
    if len(names) > 1:
        return _failed(
            device, node_id, "location_type_ambiguous",
            f"Location type {parsed.location_type!r} occurs {len(names)} times in the "
            f"hierarchy ({', '.join(names)}); it is a nestable type: {describe_chain(location)}",
            "ambiguous_match",
        ), False
    if not names:
        return _failed(
            device, node_id, "location_type_not_found",
            f"No location of type {parsed.location_type!r} in the hierarchy: "
            f"{describe_chain(location)}",
        ), False
    return set_device_attribute(device, parsed.target_attribute, names[0]), True


async def _process_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
    parsed: _ParsedConfig,
) -> tuple[str, DeviceContext, bool]:
    try:
        updated, ok = await _locate_device(
            device=device,
            node_id=node_id,
            nautobot_service=nautobot_service,
            credentials=credentials,
            parsed=parsed,
        )
    except Exception as exc:
        error = device_error_from_exception(exc, node_id=node_id, step_id=_STEP_ID)
        return device_id, fail_device_with_error(device, error), False
    return device_id, updated, ok


def _build_outcomes(
    context: WorkflowContext,
    results: list[tuple[str, DeviceContext, bool]],
) -> list[StepOutcome]:
    ok = {device_id: dev for device_id, dev, success in results if success}
    failed = {device_id: dev for device_id, dev, success in results if not success}
    outcomes = [StepOutcome(name="success", context=context.model_copy(update={"devices": ok}))]
    if failed:
        outcomes.append(
            StepOutcome(name="failure", context=context.model_copy(update={"devices": failed}))
        )
    return outcomes


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
        run.id,
        parsed.source_id,
        parsed.location_type,
        parsed.target_attribute,
        len(context.devices),
    )
    results = await asyncio.gather(
        *[
            _process_device(
                device_id=device_id,
                device=device,
                node_id=node_id,
                nautobot_service=nautobot_service,
                credentials=credentials,
                parsed=parsed,
            )
            for device_id, device in context.devices.items()
        ]
    )
    succeeded = sum(1 for _, _, ok in results if ok)
    logger.info(
        "get-device-location finished success=%d failure=%d run_id=%s",
        succeeded,
        len(results) - succeeded,
        run.id,
    )
    return _build_outcomes(context, list(results))
