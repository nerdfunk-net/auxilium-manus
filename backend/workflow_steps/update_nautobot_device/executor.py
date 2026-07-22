"""Executor for the update-nautobot-device workflow step."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

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
from repositories.settings_repository import SettingsRepository
from services.artifacts import ArtifactService
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.devices.update import DeviceUpdateService
from services.settings.source_keys import build_source_key
from workflow_steps.common.nautobot_interfaces import (
    build_interfaces_from_config,
    normalize_interfaces,
)
from workflow_steps.common.nautobot_resolve import resolve_nautobot_device_id
from workflow_steps.common.update_field_expression import (
    build_resolved_update_data,
    config_has_enabled_update_fields,
    normalize_field_spec,
)

logger = logging.getLogger(__name__)

_STEP_ID = "update-nautobot-device"


def _strip_empty(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def _resolve_device_identifier(
    *,
    config: dict[str, Any],
    device: DeviceContext,
    nautobot_device_id: str | None,
) -> dict[str, Any]:
    raw_identifier = config.get("device_identifier") or {}
    mode = "from_context"
    if isinstance(raw_identifier, dict):
        mode = str(raw_identifier.get("mode") or "from_context").strip()

    if mode == "explicit" and isinstance(raw_identifier, dict):
        explicit_id = _strip_empty(raw_identifier.get("id"))
        explicit_name = _strip_empty(raw_identifier.get("name"))
        if explicit_id or explicit_name:
            identifier: dict[str, Any] = {}
            if explicit_id:
                identifier["id"] = explicit_id
            if explicit_name:
                identifier["name"] = explicit_name
            return identifier

    identifier = {}
    if nautobot_device_id:
        identifier["id"] = nautobot_device_id
    elif device.name:
        identifier["name"] = device.name
    elif device.primary_ip4:
        identifier["ip_address"] = device.primary_ip4
    return identifier


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

    raw_update_fields = config.get("update_fields") or {}
    if not isinstance(raw_update_fields, dict):
        raise ValueError(f"{_STEP_ID}: update_fields must be an object")

    interfaces = normalize_interfaces(
        build_interfaces_from_config(config, step_id=_STEP_ID),
        str(config.get("default_prefix_length") or "/24"),
    )
    if not config_has_enabled_update_fields(raw_update_fields) and not interfaces:
        raise ValueError(
            f"{_STEP_ID}: configure at least one enabled device field or interface to update"
        )

    add_prefix = bool(config.get("add_prefix", True))
    default_prefix_length = str(config.get("default_prefix_length") or "/24")
    sync_interfaces = bool(config.get("sync_interfaces", False))

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
        raise ValueError(
            f"{_STEP_ID}: Nautobot source '{source_id}' is missing url or token"
        )

    credentials = service_factory.credentials_from_connection(nautobot_url, nautobot_token)
    nautobot_service = service_factory.get_nautobot_app_service()
    bound_client = CredentialsBoundNautobotClient(nautobot_service, credentials)
    update_service = DeviceUpdateService(bound_client)

    identifier_mode = "from_context"
    raw_identifier = config.get("device_identifier") or {}
    if isinstance(raw_identifier, dict):
        identifier_mode = str(raw_identifier.get("mode") or "from_context")

    if identifier_mode == "explicit":
        device_items: list[tuple[str, DeviceContext | None]] = [
            ("explicit", None),
        ]
    elif not context.devices:
        raise ValueError(
            f"{_STEP_ID}: no devices in workflow context; "
            "connect an inventory step or use explicit device identifier"
        )
    else:
        device_items = list(context.devices.items())

    enabled_field_count = 0
    for key, raw in raw_update_fields.items():
        if key == "custom_fields" and isinstance(raw, dict):
            enabled_field_count += sum(
                1 for item in raw.values() if normalize_field_spec(item)[0]
            )
            continue
        if normalize_field_spec(raw)[0]:
            enabled_field_count += 1

    logger.info(
        "%s started run_id=%s source_id=%s devices=%d enabled_fields=%d interfaces=%d",
        _STEP_ID,
        run.id,
        source_id,
        len(device_items),
        enabled_field_count,
        len(interfaces),
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}

    async def update_one(
        device_key: str,
        device: DeviceContext | None,
    ) -> tuple[str, DeviceContext | None, bool, str | None]:
        try:
            nautobot_device_id: str | None = None
            if device is not None:
                nautobot_device_id = await resolve_nautobot_device_id(
                    nautobot_service=nautobot_service,
                    credentials=credentials,
                    device=device,
                )
                if nautobot_device_id is None:
                    err = DeviceError(
                        node_id=node_id,
                        step_id=_STEP_ID,
                        code="not_found",
                        message=(
                            f"No Nautobot device found for workflow device {device_key} "
                            f"(name={device.name!r}, ip={device.primary_ip4!r})"
                        ),
                    )
                    failed = device.model_copy(
                        update={
                            "status": DeviceStatus.FAILED,
                            "errors": [*device.errors, err],
                        }
                    )
                    return device_key, failed, False, None

            device_identifier = _resolve_device_identifier(
                config=config,
                device=device or DeviceContext(id=device_key, name=device_key, hostname=device_key),
                nautobot_device_id=nautobot_device_id,
            )
            if not any(device_identifier.get(k) for k in ("id", "name", "ip_address")):
                raise ValueError("device identifier must include id, name, or ip_address")

            resolved_device = device or DeviceContext(
                id=device_key,
                name=device_key,
                hostname=device_key,
            )
            update_data = build_resolved_update_data(
                device=resolved_device,
                raw_fields=raw_update_fields,
                run_id=str(context.run_id) if context.run_id else None,
            )

            result = await update_service.update_device(
                device_identifier=device_identifier,
                update_data=update_data,
                interfaces=interfaces or None,
                add_prefix=add_prefix,
                default_prefix_length=default_prefix_length,
                sync_interfaces=sync_interfaces,
            )

            interfaces_failed = int(result.get("interfaces_failed") or 0)
            if interfaces_failed > 0:
                raise RuntimeError(
                    f"{interfaces_failed} interface update(s) failed for device "
                    f"{result.get('device_name') or device_key}"
                )

            if device is None:
                device_name = result.get("device_name") or device_key
                placeholder = DeviceContext(
                    id=result.get("device_id") or device_key,
                    name=device_name,
                    hostname=device_name,
                    source="nautobot",
                    status=DeviceStatus.OK,
                )
                return device_key, placeholder, True, result.get("device_id")

            enriched = device.model_copy(
                update={
                    "id": str(result.get("device_id") or device.id),
                    "name": result.get("device_name") or device.name,
                    "source": "nautobot",
                    "status": DeviceStatus.OK,
                }
            )
            return device_key, enriched, True, result.get("device_id")
        except Exception as exc:
            message = str(exc)
            if device is None:
                placeholder = DeviceContext(
                    id=device_key,
                    name=device_key,
                    hostname=device_key,
                    source="nautobot",
                    status=DeviceStatus.FAILED,
                    errors=[
                        DeviceError(
                            node_id=node_id,
                            step_id=_STEP_ID,
                            code=type(exc).__name__.lower(),
                            message=message,
                        )
                    ],
                )
                return device_key, placeholder, False, None

            err = DeviceError(
                node_id=node_id,
                step_id=_STEP_ID,
                code=type(exc).__name__.lower(),
                message=message,
            )
            failed = device.model_copy(
                update={
                    "status": DeviceStatus.FAILED,
                    "errors": [*device.errors, err],
                }
            )
            return device_key, failed, False, None

    results = await asyncio.gather(
        *[update_one(device_key, device) for device_key, device in device_items]
    )

    for device_key, updated_device, ok, _resolved_id in results:
        if updated_device is None:
            continue
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
