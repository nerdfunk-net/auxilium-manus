"""Executor for the get-nautobot-attributes step."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from repositories.settings_repository import SettingsRepository
from services.artifacts import ArtifactService
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials
from services.nautobot.devices.attribute_bag import (
    DEVICE_ATTRIBUTES_QUERY,
    attributes_from_detail,
    build_attribute_variables,
)
from services.settings.source_keys import build_source_key
from workflow_steps.common.nautobot_resolve import resolve_nautobot_device_id

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "get-nautobot-attributes"


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    list_of_attributes: list[str]


async def _fetch_device(
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
    device_id: str,
    variables: dict[str, Any],
) -> dict[str, Any] | None:
    vars_with_id = {"deviceId": device_id, **variables}
    response = await nautobot_service.graphql_query(
        DEVICE_ATTRIBUTES_QUERY, vars_with_id, credentials
    )
    device = (response.get("data") or {}).get("device")
    if device is None:
        logger.warning(
            "get-nautobot-attributes: no device data for id=%s errors=%s",
            device_id,
            response.get("errors"),
        )
    return device


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    source_id = config.get("nautobot_source_id", "").strip()
    if not source_id:
        raise ValueError("get-nautobot-attributes: nautobot_source_id is not configured")
    list_of_attributes: list[str] = config.get("list_of_attributes") or []
    return _ParsedConfig(source_id=source_id, list_of_attributes=list_of_attributes)


def _bind_nautobot(
    run: WorkflowRun, source_id: str
) -> tuple[NautobotCredentials, NautobotService]:
    db = object_session(run)
    if db is None:
        raise RuntimeError("get-nautobot-attributes: WorkflowRun has no active DB session")

    setting_key = build_source_key("nautobot", source_id)
    setting = SettingsRepository(db).get_by_key(setting_key)
    if setting is None:
        raise ValueError(
            f"get-nautobot-attributes: Nautobot source '{source_id}' not found in settings"
        )

    nautobot_url = (setting.value or {}).get("url", "").strip()
    nautobot_token = (setting.value or {}).get("token", "").strip()
    nautobot_verify_ssl = bool((setting.value or {}).get("verify_ssl", True))
    if not nautobot_url or not nautobot_token:
        raise ValueError(
            f"get-nautobot-attributes: Nautobot source '{source_id}' is missing url or token"
        )

    credentials = service_factory.credentials_from_connection(
        nautobot_url, nautobot_token, verify_ssl=nautobot_verify_ssl
    )
    nautobot_service = service_factory.get_nautobot_app_service()
    return credentials, nautobot_service


def _fail_device(
    *,
    device: DeviceContext,
    device_id: str,
    node_id: str,
    code: str,
    message: str,
) -> tuple[str, DeviceContext, bool]:
    err = DeviceError(
        node_id=node_id,
        step_id=_STEP_ID,
        code=code,
        message=message,
    )
    failed = device.model_copy(
        update={
            "status": DeviceStatus.FAILED,
            "errors": [*device.errors, err],
        }
    )
    return device_id, failed, False


async def _enrich_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
    variables: dict[str, Any],
) -> tuple[str, DeviceContext, bool]:
    try:
        nautobot_device_id = await resolve_nautobot_device_id(
            nautobot_service=nautobot_service,
            credentials=credentials,
            device=device,
        )
        if nautobot_device_id is None:
            return _fail_device(
                device=device,
                device_id=device_id,
                node_id=node_id,
                code="not_found",
                message=(
                    f"No Nautobot device found for workflow device {device_id} "
                    f"(name={device.name!r}, ip={device.primary_ip4!r})"
                ),
            )

        detail = await _fetch_device(
            nautobot_service, credentials, nautobot_device_id, variables
        )
        if detail is None:
            return _fail_device(
                device=device,
                device_id=device_id,
                node_id=node_id,
                code="not_found",
                message=f"No Nautobot data returned for device {device_id}",
            )

        platform_raw = detail.get("platform")
        platform = platform_raw if isinstance(platform_raw, dict) else {}
        attribute_bags = dict(device.attribute_bags)
        attribute_bags["nautobot"] = attributes_from_detail(detail)
        enriched = device.model_copy(
            update={
                "attribute_bags": attribute_bags,
                "platform": platform.get("name") or device.platform,
                "network_driver": platform.get("network_driver") or device.network_driver,
                "capabilities": device.capabilities | {Capability.ATTRIBUTES},
                "status": DeviceStatus.OK,
            }
        )
        return device_id, enriched, True
    except Exception as exc:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code=type(exc).__name__.lower(),
            message=str(exc),
        )


def _partition_device_results(
    results: list[tuple[str, DeviceContext, bool]],
) -> tuple[dict[str, DeviceContext], dict[str, DeviceContext]]:
    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device
    return success_devices, failed_devices


def _build_outcomes(
    context: WorkflowContext,
    success_devices: dict[str, DeviceContext],
    failed_devices: dict[str, DeviceContext],
) -> list[StepOutcome]:
    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
        )
    ]
    if failed_devices:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed_devices}),
            )
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
    del artifact_service

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    parsed = _parse_config(config)
    credentials, nautobot_service = _bind_nautobot(run, parsed.source_id)
    variables = build_attribute_variables(parsed.list_of_attributes)

    logger.info(
        "get-nautobot-attributes run_id=%s source_id=%s devices=%d attributes=%s",
        run.id,
        parsed.source_id,
        len(context.devices),
        parsed.list_of_attributes,
    )

    results = await asyncio.gather(
        *[
            _enrich_device(
                device_id=device_id,
                device=device,
                node_id=node_id,
                nautobot_service=nautobot_service,
                credentials=credentials,
                variables=variables,
            )
            for device_id, device in context.devices.items()
        ]
    )
    success_devices, failed_devices = _partition_device_results(results)
    logger.info(
        "get-nautobot-attributes returning %d/%d devices run_id=%s",
        len(success_devices),
        len(context.devices),
        run.id,
    )
    return _build_outcomes(context, success_devices, failed_devices)
