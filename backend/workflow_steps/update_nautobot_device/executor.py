"""Executor for the update-nautobot-device workflow step."""

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
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.devices.update import DeviceUpdateService
from workflow_steps.common.nautobot_interfaces import (
    build_interfaces_from_config,
    normalize_interfaces,
)
from workflow_steps.common.nautobot_resolve import resolve_nautobot_device_id
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.update_field_expression import (
    build_resolved_update_data,
    config_has_enabled_update_fields,
    normalize_field_spec,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "update-nautobot-device"


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    raw_update_fields: dict[str, Any]
    interfaces: list[dict[str, Any]]
    add_prefix: bool
    default_prefix_length: str
    sync_interfaces: bool
    identifier_mode: str


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


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
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

    raw_identifier = config.get("device_identifier") or {}
    identifier_mode = "from_context"
    if isinstance(raw_identifier, dict):
        identifier_mode = str(raw_identifier.get("mode") or "from_context")

    return _ParsedConfig(
        source_id=source_id,
        raw_update_fields=raw_update_fields,
        interfaces=interfaces,
        add_prefix=bool(config.get("add_prefix", True)),
        default_prefix_length=str(config.get("default_prefix_length") or "/24"),
        sync_interfaces=bool(config.get("sync_interfaces", False)),
        identifier_mode=identifier_mode,
    )


def _resolve_device_items(
    identifier_mode: str, context: WorkflowContext
) -> list[tuple[str, DeviceContext | None]]:
    if identifier_mode == "explicit":
        return [("explicit", None)]
    if not context.devices:
        raise ValueError(
            f"{_STEP_ID}: no devices in workflow context; "
            "connect an inventory step or use explicit device identifier"
        )
    return list(context.devices.items())


def _count_enabled_fields(raw_update_fields: dict[str, Any]) -> int:
    enabled_field_count = 0
    for key, raw in raw_update_fields.items():
        if key == "custom_fields" and isinstance(raw, dict):
            enabled_field_count += sum(1 for item in raw.values() if normalize_field_spec(item)[0])
            continue
        if normalize_field_spec(raw)[0]:
            enabled_field_count += 1
    return enabled_field_count


def _build_update_service(
    db: Any, source_id: str
) -> tuple[NautobotService, NautobotCredentials, DeviceUpdateService]:
    credentials = resolve_nautobot_credentials(db, source_id, step_id=_STEP_ID)
    nautobot_service = service_factory.get_nautobot_app_service()
    bound_client = CredentialsBoundNautobotClient(nautobot_service, credentials)
    return nautobot_service, credentials, DeviceUpdateService(bound_client)


def _fail_device(
    *,
    device_key: str,
    device: DeviceContext | None,
    node_id: str,
    code: str | None = None,
    message: str | None = None,
    exc: Exception | None = None,
) -> tuple[str, DeviceContext | None, bool, str | None]:
    error_code = code or (type(exc).__name__.lower() if exc is not None else "error")
    error_message = message or (str(exc) if exc is not None else "Unknown error")

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
                    code=error_code,
                    message=error_message,
                )
            ],
        )
        return device_key, placeholder, False, None

    err = DeviceError(
        node_id=node_id,
        step_id=_STEP_ID,
        code=error_code,
        message=error_message,
    )
    failed = device.model_copy(
        update={
            "status": DeviceStatus.FAILED,
            "errors": [*device.errors, err],
        }
    )
    return device_key, failed, False, None


def _apply_update_result(
    *,
    device_key: str,
    device: DeviceContext | None,
    result: dict[str, Any],
) -> tuple[str, DeviceContext | None, bool, str | None]:
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


async def _update_one_device(
    *,
    device_key: str,
    device: DeviceContext | None,
    config: dict[str, Any],
    context: WorkflowContext,
    node_id: str,
    nautobot_service: NautobotService,
    credentials: NautobotCredentials,
    update_service: DeviceUpdateService,
    parsed: _ParsedConfig,
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
                return _fail_device(
                    device_key=device_key,
                    device=device,
                    node_id=node_id,
                    code="not_found",
                    message=(
                        f"No Nautobot device found for workflow device {device_key} "
                        f"(name={device.name!r}, ip={device.primary_ip4!r})"
                    ),
                )

        device_identifier = _resolve_device_identifier(
            config=config,
            device=device or DeviceContext(id=device_key, name=device_key, hostname=device_key),
            nautobot_device_id=nautobot_device_id,
        )
        if not any(device_identifier.get(k) for k in ("id", "name", "ip_address")):
            raise ValueError("device identifier must include id, name, or ip_address")

        resolved = device or DeviceContext(id=device_key, name=device_key, hostname=device_key)
        result = await update_service.update_device(
            device_identifier=device_identifier,
            update_data=build_resolved_update_data(
                device=resolved,
                raw_fields=parsed.raw_update_fields,
                run_id=str(context.run_id) if context.run_id else None,
            ),
            interfaces=parsed.interfaces or None,
            add_prefix=parsed.add_prefix,
            default_prefix_length=parsed.default_prefix_length,
            sync_interfaces=parsed.sync_interfaces,
        )
        if int(result.get("interfaces_failed") or 0) > 0:
            raise RuntimeError(
                f"{result.get('interfaces_failed')} interface update(s) failed for device "
                f"{result.get('device_name') or device_key}"
            )
        return _apply_update_result(device_key=device_key, device=device, result=result)
    except Exception as exc:
        return _fail_device(
            device_key=device_key, device=device, node_id=node_id, exc=exc
        )


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

    parsed = _parse_config(config)

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    nautobot_service, credentials, update_service = _build_update_service(db, parsed.source_id)
    device_items = _resolve_device_items(parsed.identifier_mode, context)
    enabled_field_count = _count_enabled_fields(parsed.raw_update_fields)

    logger.info(
        "%s started run_id=%s source_id=%s devices=%d enabled_fields=%d interfaces=%d",
        _STEP_ID,
        run.id,
        parsed.source_id,
        len(device_items),
        enabled_field_count,
        len(parsed.interfaces),
    )

    results = await asyncio.gather(
        *[
            _update_one_device(
                device_key=device_key,
                device=device,
                config=config,
                context=context,
                node_id=node_id,
                nautobot_service=nautobot_service,
                credentials=credentials,
                update_service=update_service,
                parsed=parsed,
            )
            for device_key, device in device_items
        ]
    )

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
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

    return _build_outcomes(context, success_devices, failed_devices)
