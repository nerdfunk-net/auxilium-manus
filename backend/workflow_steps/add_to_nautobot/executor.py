"""Executor for the add-to-nautobot workflow step."""

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
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.devices.creation import DeviceCreationService
from services.nautobot.devices.types import AddDeviceRequest
from services.settings.source_keys import build_source_key
from workflow_steps.common.nautobot_interfaces import (
    build_interfaces_from_config,
    normalize_interfaces,
)
from workflow_steps.common.update_field_expression import build_resolved_update_data

logger = logging.getLogger(__name__)

_STEP_ID = "add-to-nautobot"
_REQUIRED_FIELDS = ("name", "role", "status", "location", "device_type")


def _tags_as_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value
    return [str(value)]


def _position_as_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        logger.warning("%s: position '%s' is not an integer — omitting", _STEP_ID, text)
        return None


def _build_request(
    *,
    resolved: dict[str, Any],
    config: dict[str, Any],
    interfaces: list[dict[str, Any]],
) -> AddDeviceRequest:
    virtual_chassis = config.get("virtual_chassis") or {}
    vc_mode = str(virtual_chassis.get("mode") or "none").strip()

    return AddDeviceRequest(
        name=resolved["name"],
        role=resolved["role"],
        status=resolved["status"],
        location=resolved["location"],
        device_type=resolved["device_type"],
        platform=resolved.get("platform"),
        software_version=resolved.get("software_version"),
        serial=resolved.get("serial"),
        asset_tag=resolved.get("asset_tag"),
        tags=_tags_as_list(resolved.get("tags")),
        custom_fields=resolved.get("custom_fields"),
        rack=resolved.get("rack"),
        face=resolved.get("face"),
        position=_position_as_int(resolved.get("position")),
        interfaces=interfaces,
        add_prefix=bool(config.get("add_prefix", True)),
        default_prefix_length=str(config.get("default_prefix_length") or "/24"),
        virtual_chassis_id=str(virtual_chassis.get("id") or "").strip() or None
        if vc_mode == "join"
        else None,
        new_virtual_chassis_name=str(virtual_chassis.get("name") or "").strip() or None
        if vc_mode == "create"
        else None,
        dry_run=bool(config.get("dry_run", False)),
    )


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del artifact_service

    source_id = str(config.get("nautobot_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is not configured")

    raw_device_fields = config.get("device_fields") or {}
    if not isinstance(raw_device_fields, dict):
        raise ValueError(f"{_STEP_ID}: device_fields must be an object")

    interfaces = normalize_interfaces(
        build_interfaces_from_config(config, step_id=_STEP_ID),
        str(config.get("default_prefix_length") or "/24"),
    )

    if not context.devices:
        raise ValueError(
            f"{_STEP_ID}: no devices in workflow context; "
            "connect an inventory step upstream (e.g. get-from-list)"
        )

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    setting_key = build_source_key("nautobot", source_id)
    setting = SettingsRepository(db).get_by_key(setting_key)
    if setting is None:
        raise ValueError(f"{_STEP_ID}: Nautobot source '{source_id}' not found in settings")

    nautobot_url = (setting.value or {}).get("url", "").strip()
    nautobot_token = (setting.value or {}).get("token", "").strip()
    if not nautobot_url or not nautobot_token:
        raise ValueError(f"{_STEP_ID}: Nautobot source '{source_id}' is missing url or token")

    credentials = service_factory.credentials_from_connection(nautobot_url, nautobot_token)
    nautobot_service = service_factory.get_nautobot_app_service()
    bound_client = CredentialsBoundNautobotClient(nautobot_service, credentials)
    creation_service = DeviceCreationService(bound_client)

    device_items = list(context.devices.items())
    run_id = str(context.run_id) if context.run_id else None

    logger.info(
        "%s started run_id=%s source_id=%s devices=%d interfaces=%d",
        _STEP_ID,
        run.id,
        source_id,
        len(device_items),
        len(interfaces),
    )

    async def create_one(device_key: str, device: DeviceContext) -> tuple[str, DeviceContext, bool]:
        try:
            resolved = build_resolved_update_data(
                device=device, raw_fields=raw_device_fields, run_id=run_id
            )
            missing = [key for key in _REQUIRED_FIELDS if not resolved.get(key)]
            if missing:
                err = DeviceError(
                    node_id=node_id,
                    step_id=_STEP_ID,
                    code="missing_required_field",
                    message=(f"Required field(s) could not be resolved: {', '.join(missing)}"),
                )
                failed = device.model_copy(
                    update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
                )
                return device_key, failed, False

            request = _build_request(resolved=resolved, config=config, interfaces=interfaces)
            result = await creation_service.create_device(request)

            if request.dry_run:
                if not result.get("success"):
                    err = DeviceError(
                        node_id=node_id,
                        step_id=_STEP_ID,
                        code="dry_run_validation_failed",
                        message="; ".join(result.get("errors") or ["dry run validation failed"]),
                    )
                    failed = device.model_copy(
                        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
                    )
                    return device_key, failed, False
                enriched = device.model_copy(
                    update={
                        "status": DeviceStatus.OK,
                        "capabilities": device.capabilities | {Capability.ATTRIBUTES},
                    }
                )
                return device_key, enriched, True

            enriched = device.model_copy(
                update={
                    "id": str(result["device_id"]),
                    "name": result.get("device_name") or device.name,
                    "source": "nautobot",
                    "status": DeviceStatus.OK,
                    "attribute_bags": {
                        **device.attribute_bags,
                        "nautobot": result.get("device") or {},
                    },
                    "capabilities": device.capabilities | {Capability.ATTRIBUTES},
                }
            )
            return device_key, enriched, True
        except Exception as exc:
            err = DeviceError(
                node_id=node_id,
                step_id=_STEP_ID,
                code=type(exc).__name__.lower(),
                message=str(exc),
            )
            failed = device.model_copy(
                update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
            )
            return device_key, failed, False

    results = await asyncio.gather(
        *[create_one(device_key, device) for device_key, device in device_items]
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    for device_key, updated_device, ok in results:
        if ok:
            success_devices[device_key] = updated_device
        else:
            failed_devices[device_key] = updated_device

    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        len(success_devices),
        len(failed_devices),
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
