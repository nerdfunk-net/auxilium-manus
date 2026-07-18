"""Executor for the get-nautobot-attributes step."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

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

logger = logging.getLogger(__name__)


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


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del artifact_service  # unused for this step

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    source_id = config.get("nautobot_source_id", "").strip()
    if not source_id:
        raise ValueError("get-nautobot-attributes: nautobot_source_id is not configured")

    list_of_attributes: list[str] = config.get("list_of_attributes") or []

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
    if not nautobot_url or not nautobot_token:
        raise ValueError(
            f"get-nautobot-attributes: Nautobot source '{source_id}' is missing url or token"
        )

    credentials = service_factory.credentials_from_connection(nautobot_url, nautobot_token)
    nautobot_service = service_factory.get_nautobot_app_service()

    variables = build_attribute_variables(list_of_attributes)

    logger.info(
        "get-nautobot-attributes run_id=%s source_id=%s devices=%d attributes=%s",
        run.id,
        source_id,
        len(context.devices),
        list_of_attributes,
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def enrich_device(
        device_id: str,
        device: DeviceContext,
    ) -> tuple[str, DeviceContext, bool]:
        try:
            nautobot_device_id = await resolve_nautobot_device_id(
                nautobot_service=nautobot_service,
                credentials=credentials,
                device=device,
            )
            if nautobot_device_id is None:
                err = DeviceError(
                    node_id=node_id,
                    step_id="get-nautobot-attributes",
                    code="not_found",
                    message=(
                        f"No Nautobot device found for workflow device {device_id} "
                        f"(name={device.name!r}, ip={device.primary_ip4!r})"
                    ),
                )
                failed = device.model_copy(
                    update={
                        "status": DeviceStatus.FAILED,
                        "errors": [*device.errors, err],
                    }
                )
                return device_id, failed, False

            detail = await _fetch_device(
                nautobot_service, credentials, nautobot_device_id, variables
            )
            if detail is None:
                err = DeviceError(
                    node_id=node_id,
                    step_id="get-nautobot-attributes",
                    code="not_found",
                    message=f"No Nautobot data returned for device {device_id}",
                )
                failed = device.model_copy(
                    update={
                        "status": DeviceStatus.FAILED,
                        "errors": [*device.errors, err],
                    }
                )
                return device_id, failed, False

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
            err = DeviceError(
                node_id=node_id,
                step_id="get-nautobot-attributes",
                code=type(exc).__name__.lower(),
                message=str(exc),
            )
            failed = device.model_copy(
                update={
                    "status": DeviceStatus.FAILED,
                    "errors": [*device.errors, err],
                }
            )
            return device_id, failed, False

    results = await asyncio.gather(
        *[enrich_device(device_id, device) for device_id, device in context.devices.items()]
    )

    for device_id, updated_device, ok in results:
        if ok:
            success_devices[device_id] = updated_device
        else:
            failed_devices[device_id] = updated_device

    logger.info(
        "get-nautobot-attributes returning %d/%d devices run_id=%s",
        len(success_devices),
        len(context.devices),
        run.id,
    )

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
