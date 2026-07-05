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
from workflow_steps.common.nautobot_resolve import resolve_nautobot_device_id
from workflow_steps.common.nautobot_update_fields import (
    context_has_nautobot_update_fields,
    extract_update_fields_from_nautobot_bag,
    merge_update_data,
)

logger = logging.getLogger(__name__)

_STEP_ID = "update-nautobot-device"

_DEVICE_FIELD_KEYS = (
    "name",
    "location",
    "serial",
    "role",
    "status",
    "device_type",
    "platform",
    "software_version",
    "asset_tag",
    "tags",
    "custom_fields",
    "primary_ip4",
    "rack",
    "position",
    "face",
)


def _strip_empty(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


def _build_update_data(config: dict[str, Any]) -> dict[str, Any]:
    raw_fields = config.get("update_fields") or {}
    if not isinstance(raw_fields, dict):
        raise ValueError(f"{_STEP_ID}: update_fields must be an object")

    update_data: dict[str, Any] = {}
    for key in _DEVICE_FIELD_KEYS:
        if key not in raw_fields:
            continue
        value = raw_fields[key]
        if key == "tags":
            if isinstance(value, list):
                cleaned = [str(item).strip() for item in value if str(item).strip()]
                if cleaned:
                    update_data[key] = cleaned
            elif isinstance(value, str) and value.strip():
                update_data[key] = value
            continue
        if key == "custom_fields":
            if isinstance(value, dict) and value:
                cleaned_cf = {
                    str(k): str(v)
                    for k, v in value.items()
                    if str(k).strip() and str(v).strip()
                }
                if cleaned_cf:
                    update_data[key] = cleaned_cf
            continue
        cleaned = _strip_empty(value)
        if cleaned is not None:
            update_data[key] = cleaned
    return update_data


def _normalize_interfaces(
    interfaces: list[dict[str, Any]],
    default_prefix_length: str,
) -> list[dict[str, Any]]:
    suffix = (
        default_prefix_length
        if default_prefix_length.startswith("/")
        else f"/{default_prefix_length.lstrip('/')}"
    )
    normalized: list[dict[str, Any]] = []
    for item in interfaces:
        iface = dict(item)
        ip_address = iface.get("ip_address")
        if isinstance(ip_address, str) and ip_address.strip() and "/" not in ip_address:
            iface["ip_address"] = f"{ip_address.strip()}{suffix}"
        normalized.append(iface)
    return normalized


def _build_interfaces(config: dict[str, Any]) -> list[dict[str, Any]]:
    raw_interfaces = config.get("interfaces") or []
    if not isinstance(raw_interfaces, list):
        raise ValueError(f"{_STEP_ID}: interfaces must be a list")

    interfaces: list[dict[str, Any]] = []
    for item in raw_interfaces:
        if not isinstance(item, dict):
            continue
        name = _strip_empty(item.get("name"))
        if not name:
            continue
        iface: dict[str, Any] = {"name": name}
        for field in (
            "type",
            "status",
            "ip_address",
            "namespace",
            "description",
            "enabled",
            "mgmt_only",
            "mac_address",
            "mtu",
            "mode",
            "ip_role",
        ):
            if field not in item:
                continue
            value = item[field]
            if field in {"enabled", "mgmt_only"}:
                if value is not None:
                    iface[field] = bool(value)
                continue
            cleaned = _strip_empty(value)
            if cleaned is not None:
                iface[field] = cleaned
        if item.get("is_primary_ipv4"):
            iface["is_primary_ipv4"] = True
        interfaces.append(iface)
    return interfaces


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

    config_update_data = _build_update_data(config)
    interfaces = _normalize_interfaces(
        _build_interfaces(config),
        str(config.get("default_prefix_length") or "/24"),
    )
    has_context_updates = context_has_nautobot_update_fields(context.devices)
    if not config_update_data and not interfaces and not has_context_updates:
        raise ValueError(
            f"{_STEP_ID}: configure at least one device field or interface to update"
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
            f"{_STEP_ID}: no devices in workflow context; connect an inventory step or use explicit device identifier"
        )
    else:
        device_items = list(context.devices.items())

    logger.info(
        "%s run_id=%s source_id=%s devices=%d fields=%d interfaces=%d",
        _STEP_ID,
        run.id,
        source_id,
        len(device_items),
        len(config_update_data),
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

            bag_update_data: dict[str, Any] = {}
            if device is not None:
                nautobot_bag = device.attribute_bags.get("nautobot")
                if isinstance(nautobot_bag, dict):
                    bag_update_data = extract_update_fields_from_nautobot_bag(nautobot_bag)
            update_data = merge_update_data(config_update_data, bag_update_data)

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
