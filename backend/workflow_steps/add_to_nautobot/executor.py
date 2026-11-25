"""Executor for the add-to-nautobot workflow step."""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import service_factory
from core.models.runs import WorkflowRun
from models.failure import FailureInfo, failure_from_exception
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.nautobot.common.exceptions import NautobotAPIError, is_duplicate_error
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.devices.creation import DeviceCreationService
from services.nautobot.devices.types import AddDeviceRequest
from workflow_steps.common.failure_records import INVALID_INPUT
from workflow_steps.common.interface_payload import (
    build_interfaces_from_config,
    interfaces_from_nautobot_bag,
    normalize_interfaces,
)
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.nautobot_update_fields import extract_update_fields_from_nautobot_bag
from workflow_steps.common.partial_outcomes import NAUTOBOT_TEXT, device_error_from_exception
from workflow_steps.common.redundancy_groups_config import (
    DEFAULT_REDUNDANCY_STATUS,
    parse_redundancy_groups,
)
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.run_session import require_session
from workflow_steps.common.step_flags import parse_bool_flag, record_dry_run
from workflow_steps.common.value_expression import build_resolved_update_data

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "add-to-nautobot"
_REQUIRED_FIELDS = ("name", "role", "status", "location", "device_type")
_SOURCE_MODES = frozenset({"manual", "nautobot_origin"})
_VC_MODES = frozenset({"none", "join", "create"})
# Fields of a REST 400 that a device-name uniqueness error is reported under: the whole object
# (name + location + tenant) or ``name`` alone, depending on DEVICE_UNIQUENESS.
_NAME_UNIQUENESS_FIELDS = frozenset({"__all__", "non_field_errors", "name"})


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    raw_device_fields: dict[str, Any]
    custom_fields_source: str
    interfaces_source: str
    default_prefix_length: str
    manual_interfaces: list[dict[str, Any]]
    refresh_attributes_after_create: bool
    # None = redundancy groups are not written; otherwise the name schema, e.g. "hsrp-{next}".
    redundancy_name_pattern: str | None = None
    redundancy_group_status: str = DEFAULT_REDUNDANCY_STATUS
    # Read once at the top (a bad value fails the step once, not every device).
    add_prefix: bool = True
    dry_run: bool = False
    virtual_chassis_mode: str = "none"
    virtual_chassis_id: str | None = None
    virtual_chassis_name: str | None = None


def _all_custom_fields_from_bag(device: DeviceContext) -> dict[str, str] | None:
    bag = device.attribute_bags.get("nautobot") or {}
    extracted = extract_update_fields_from_nautobot_bag({"custom_fields": bag.get("custom_fields")})
    return extracted.get("custom_fields")


def _tags_as_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return value
    return [str(value)]


_WHOLE_NUMBER = re.compile(r"[0-9]+")


def _position_as_int(value: Any) -> int | None:
    """A rack position from a resolved text; blank is no position, anything else must be digits.

    ``int()`` also takes ``"1_0"`` and non-ASCII digits, and the old fallback dropped a bad value
    silently and created the device without it.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not _WHOLE_NUMBER.fullmatch(text):
        raise _PositionError(f"position must be a whole number, got {text!r}")
    return int(text)


class _PositionError(ValueError):
    """The resolved ``position`` is not a whole number (fails that device)."""


def _build_request(
    *,
    resolved: dict[str, Any],
    parsed: _ParsedConfig,
    interfaces: list[dict[str, Any]],
) -> AddDeviceRequest:
    return AddDeviceRequest(
        name=resolved["name"],
        role=resolved["role"],
        status=resolved["status"],
        location=resolved["location"],
        device_type=resolved["device_type"],
        platform=resolved.get("platform"),
        secrets_group=resolved.get("secrets_group"),
        software_version=resolved.get("software_version"),
        serial=resolved.get("serial"),
        asset_tag=resolved.get("asset_tag"),
        tags=_tags_as_list(resolved.get("tags")),
        custom_fields=resolved.get("custom_fields"),
        rack=resolved.get("rack"),
        face=resolved.get("face"),
        position=_position_as_int(resolved.get("position")),
        interfaces=interfaces,
        redundancy_name_pattern=parsed.redundancy_name_pattern,
        redundancy_group_status=parsed.redundancy_group_status,
        add_prefix=parsed.add_prefix,
        default_prefix_length=parsed.default_prefix_length,
        virtual_chassis_id=parsed.virtual_chassis_id,
        new_virtual_chassis_name=parsed.virtual_chassis_name,
        dry_run=parsed.dry_run,
    )


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    source_id = str(config.get("nautobot_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is not configured")

    raw_device_fields = config.get("device_fields") or {}
    if not isinstance(raw_device_fields, dict):
        raise ValueError(f"{_STEP_ID}: device_fields must be an object")

    custom_fields_source = str(config.get("custom_fields_source") or "manual").strip().lower()
    if custom_fields_source not in _SOURCE_MODES:
        raise ValueError(
            f"{_STEP_ID}: custom_fields_source must be one of {sorted(_SOURCE_MODES)}, "
            f"got {custom_fields_source!r}"
        )

    interfaces_source = str(config.get("interfaces_source") or "manual").strip().lower()
    if interfaces_source not in _SOURCE_MODES:
        raise ValueError(
            f"{_STEP_ID}: interfaces_source must be one of {sorted(_SOURCE_MODES)}, "
            f"got {interfaces_source!r}"
        )

    default_prefix_length = str(config.get("default_prefix_length") or "/24")
    manual_interfaces = normalize_interfaces(
        build_interfaces_from_config(config, step_id=_STEP_ID),
        default_prefix_length,
    )

    redundancy_name_pattern, redundancy_group_status = parse_redundancy_groups(
        config, step_id=_STEP_ID, interfaces_source=interfaces_source
    )

    virtual_chassis = config.get("virtual_chassis") or {}
    if not isinstance(virtual_chassis, dict):
        raise ValueError(f"{_STEP_ID}: virtual_chassis must be an object")
    vc_mode = str(virtual_chassis.get("mode") or "none").strip().lower()
    if vc_mode not in _VC_MODES:
        raise ValueError(
            f"{_STEP_ID}: virtual_chassis.mode must be one of {sorted(_VC_MODES)}, got {vc_mode!r}"
        )

    return _ParsedConfig(
        source_id=source_id,
        raw_device_fields=raw_device_fields,
        custom_fields_source=custom_fields_source,
        interfaces_source=interfaces_source,
        default_prefix_length=default_prefix_length,
        manual_interfaces=manual_interfaces,
        refresh_attributes_after_create=parse_bool_flag(
            config, "refresh_attributes_after_create", default=True
        ),
        redundancy_name_pattern=redundancy_name_pattern,
        redundancy_group_status=redundancy_group_status,
        add_prefix=parse_bool_flag(config, "add_prefix", default=True, step_id=_STEP_ID),
        dry_run=parse_bool_flag(config, "dry_run", default=False, step_id=_STEP_ID),
        virtual_chassis_mode=vc_mode,
        virtual_chassis_id=(
            str(virtual_chassis.get("id") or "").strip() or None if vc_mode == "join" else None
        ),
        virtual_chassis_name=(
            str(virtual_chassis.get("name") or "").strip() or None if vc_mode == "create" else None
        ),
    )


def _bind_creation_service(db: Any, source_id: str) -> DeviceCreationService:
    credentials = resolve_nautobot_credentials(db, source_id, step_id=_STEP_ID)
    nautobot_service = service_factory.get_nautobot_app_service()
    bound_client = CredentialsBoundNautobotClient(nautobot_service, credentials)
    return DeviceCreationService(bound_client)


def _is_already_exists(exc: Exception) -> bool:
    """Distinguish Nautobot's uniqueness-violation 400 from any other API
    failure, so a workflow can route the failure outcome by ``error.code``
    (device_already_exists -> update instead of create) rather than treat
    every rejection the same way. Reuses the shared classifier already used
    by ``services.nautobot.devices.common`` for the same distinction.
    """
    if not (isinstance(exc, NautobotAPIError) and is_duplicate_error(exc)):
        return False
    # "already exists" is also said for other unique fields (asset tag): only a name clash may be
    # routed to an update by name, so a 400 that names any other field does not count.
    return exc.fields is None or set(exc.fields) <= _NAME_UNIQUENESS_FIELDS


def _create_failure(exc: Exception) -> FailureInfo | None:
    """A duplicate the API did not flag as 409 is still ``already_exists`` for the assistant."""
    if _is_already_exists(exc):
        return FailureInfo(phase="api", kind="already_exists", exception_type=type(exc).__name__)
    return failure_from_exception(exc)


def _fail_device(
    *,
    device: DeviceContext,
    device_key: str,
    node_id: str,
    code: str,
    message: str,
    failure: FailureInfo | None = None,
) -> tuple[str, DeviceContext, bool]:
    err = DeviceError(
        node_id=node_id,
        step_id=_STEP_ID,
        code=code,
        message=message,
        failure=failure,
    )
    failed = device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )
    return device_key, failed, False


async def _create_one_device(
    *,
    device_key: str,
    device: DeviceContext,
    node_id: str,
    config: dict[str, Any],
    run_id: str | None,
    parsed: _ParsedConfig,
    creation_service: DeviceCreationService,
) -> tuple[str, DeviceContext, bool]:
    try:
        resolved = build_resolved_update_data(
            device=device, raw_fields=parsed.raw_device_fields, run_id=run_id
        )

        if parsed.custom_fields_source == "nautobot_origin":
            all_custom_fields = _all_custom_fields_from_bag(device)
            if all_custom_fields:
                resolved["custom_fields"] = all_custom_fields
            else:
                resolved.pop("custom_fields", None)

        if parsed.interfaces_source == "nautobot_origin":
            interfaces = interfaces_from_nautobot_bag(
                device.attribute_bags.get("nautobot"),
                default_prefix_length=parsed.default_prefix_length,
            )
        else:
            interfaces = parsed.manual_interfaces

        missing = [key for key in _REQUIRED_FIELDS if not resolved.get(key)]
        if missing:
            return _fail_device(
                device=device,
                device_key=device_key,
                node_id=node_id,
                code="missing_required_field",
                failure=INVALID_INPUT,
                message=(f"Required field(s) could not be resolved: {', '.join(missing)}"),
            )

        request = _build_request(resolved=resolved, parsed=parsed, interfaces=interfaces)
        result = await creation_service.create_device(request)

        if request.dry_run:
            if not result.get("success"):
                return _fail_device(
                    device=device,
                    device_key=device_key,
                    node_id=node_id,
                    code="dry_run_validation_failed",
                    failure=INVALID_INPUT,
                    message="; ".join(result.get("errors") or ["dry run validation failed"]),
                )
            enriched = device.model_copy(
                update={
                    "status": DeviceStatus.OK,
                    "capabilities": device.capabilities | {Capability.ATTRIBUTES},
                }
            )
            enriched = record_dry_run(
                enriched,
                node_id=node_id,
                payload={
                    "validated": True,
                    "would_create_device": request.name,
                    "would_create_interfaces": [
                        str(iface.get("name") or "") for iface in interfaces
                    ],
                },
            )
            return device_key, enriched, True

        if not result.get("success"):
            # Pre-flight checks failed: nothing was created in Nautobot.
            return _fail_device(
                device=device,
                device_key=device_key,
                node_id=node_id,
                code="preflight_failed",
                message="; ".join(str(e) for e in result.get("errors") or [])
                or "pre-flight checks failed",
                failure=FailureInfo(phase="api", kind="bad_request"),
            )

        problems: list[str] = []
        if int(result.get("interfaces_failed") or 0) > 0:
            problems.append(f"{result['interfaces_failed']} interface(s) could not be created")
        problems.extend(str(warning) for warning in result.get("warnings") or [])
        if problems:
            # The device exists in Nautobot now: keep its id on the failed device so an
            # update-nautobot-device step on the 'failure' branch can repair it.
            created = device.model_copy(
                update={"id": str(result.get("device_id") or device.id), "source": "nautobot"}
            )
            return _fail_device(
                device=created,
                device_key=device_key,
                node_id=node_id,
                code="device_created_incomplete",
                message="; ".join(problems),
                failure=FailureInfo(phase="api", kind="server_error"),
            )

        update_fields: dict[str, Any] = {
            "name": result.get("device_name") or device.name,
            "status": DeviceStatus.OK,
            "capabilities": device.capabilities | {Capability.ATTRIBUTES},
        }
        if parsed.refresh_attributes_after_create:
            # Merge (never replace) the freshly created device's REST response into
            # the existing bag: it has no `interfaces` key (device interfaces are a
            # separate Nautobot resource), so a wholesale replace here silently wiped
            # out `interfaces`/anything else an upstream step (e.g.
            # config-to-attributes) had already written into `attribute_bags.nautobot`
            # for a later `update-nautobot-device` step to push.
            existing_bag = device.attribute_bags.get("nautobot") or {}
            update_fields["id"] = str(result["device_id"])
            update_fields["source"] = "nautobot"
            update_fields["attribute_bags"] = {
                **device.attribute_bags,
                "nautobot": {**existing_bag, **(result.get("device") or {})},
            }

        enriched = device.model_copy(update=update_fields)
        return device_key, enriched, True
    except Exception as exc:
        if isinstance(exc, _PositionError):
            code = "invalid_position"
        elif _is_already_exists(exc):
            code = "device_already_exists"
        else:
            code = type(exc).__name__.lower()
        error = device_error_from_exception(
            exc, node_id=node_id, step_id=_STEP_ID, keep_text=NAUTOBOT_TEXT
        )
        return _fail_device(
            device=device,
            device_key=device_key,
            node_id=node_id,
            code=code,
            message=error.message,
            failure=_create_failure(exc) or error.failure,
        )


def _partition_and_build_outcomes(
    *,
    context: WorkflowContext,
    results: list[tuple[str, DeviceContext, bool]],
) -> list[StepOutcome]:
    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    for device_key, updated_device, ok in results:
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

    # An empty branch (e.g. the "non_existing" side of an exists-in-nautobot split when
    # everything exists) is a no-op, not an error.
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    db = require_session(run, _STEP_ID)

    creation_service = _bind_creation_service(db, parsed.source_id)
    device_items = list(context.devices.items())
    run_id = str(context.run_id) if context.run_id else None

    logger.info(
        "%s started run_id=%s source_id=%s devices=%d custom_fields_source=%s interfaces_source=%s",
        _STEP_ID,
        log_run_id(run),
        parsed.source_id,
        len(device_items),
        parsed.custom_fields_source,
        parsed.interfaces_source,
    )

    results = await asyncio.gather(
        *[
            _create_one_device(
                device_key=device_key,
                device=device,
                node_id=node_id,
                config=config,
                run_id=run_id,
                parsed=parsed,
                creation_service=creation_service,
            )
            for device_key, device in device_items
        ]
    )

    success_count = sum(1 for _, _, ok in results if ok)
    failed_count = len(results) - success_count
    logger.info(
        "%s finished success=%d failure=%d run_id=%s",
        _STEP_ID,
        success_count,
        failed_count,
        log_run_id(run),
    )

    return _partition_and_build_outcomes(context=context, results=results)
