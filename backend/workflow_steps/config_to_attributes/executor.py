"""Executor for the config-to-attributes step."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from workflow_steps.common.attribute_defaults import merge_nautobot_defaults
from workflow_steps.common.failure_records import MISSING_DATA
from workflow_steps.common.partial_outcomes import mark_device_failed
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.common.step_flags import parse_bool_flag
from workflow_steps.config_to_attributes.config import get_config
from workflow_steps.config_to_attributes.formats import SOURCE_FORMATS, SourceFormat
from workflow_steps.config_to_attributes.primary_ipv4 import (
    PRIORITY_STRATEGIES,
    device_primary_ip_present,
    find_interface_for_ip,
    mark_primary,
    select_primary_ipv4,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "config-to-attributes"
_CONFIG_SOURCES = frozenset({"running", "startup"})
_SUPPORTED_ATTRIBUTES = frozenset({"interfaces", "device"})


@dataclass(frozen=True)
class _ParsedConfig:
    config_source: str
    parsed_key: str
    attributes: frozenset[str]
    source_format: SourceFormat
    update_primary_ipv4: bool
    primary_ipv4_priority: list[str]
    primary_ipv4_custom_pattern: str


@dataclass(frozen=True)
class _DeviceResult:
    """One device after mapping: ``device`` is ``None`` when it had no usable parsed data."""

    device: DeviceContext | None = None
    interfaces_written: int = 0
    note: str | None = None
    primary_failure: str | None = None


def _parse_source_format(config: dict[str, Any]) -> SourceFormat:
    raw = str(config.get("source_format") or get_config()["source_format"]).strip().lower()
    if raw not in SOURCE_FORMATS:
        raise ValueError(
            f"{_STEP_ID}: source_format must be one of {sorted(SOURCE_FORMATS)}, got {raw!r}"
        )
    return SOURCE_FORMATS[raw]


def _parse_attributes(config: dict[str, Any]) -> frozenset[str]:
    raw = config["attributes"] if "attributes" in config else get_config()["attributes"]
    if not isinstance(raw, list):
        return frozenset()
    chosen = {str(item).strip() for item in raw if str(item).strip()}
    unknown = chosen - _SUPPORTED_ATTRIBUTES
    if unknown:
        raise ValueError(
            f"{_STEP_ID}: unknown attributes {sorted(unknown)}, "
            f"allowed: {sorted(_SUPPORTED_ATTRIBUTES)}"
        )
    return frozenset(chosen)


def _parse_config_source(config: dict[str, Any]) -> str:
    raw = str(config.get("config_source") or get_config()["config_source"]).strip().lower()
    if raw not in _CONFIG_SOURCES:
        raise ValueError(
            f"{_STEP_ID}: config_source must be one of {sorted(_CONFIG_SOURCES)}, got {raw!r}"
        )
    return raw


def _parse_parsed_key(config: dict[str, Any]) -> str:
    raw = str(config.get("parsed_key") or get_config()["parsed_key"]).strip()
    if not raw:
        raise ValueError(f"{_STEP_ID}: parsed_key is required")
    return raw


def _parse_primary_ipv4_priority(config: dict[str, Any]) -> list[str]:
    raw = (
        config["primary_ipv4_priority"]
        if "primary_ipv4_priority" in config
        else get_config()["primary_ipv4_priority"]
    )
    if not isinstance(raw, list):
        raise ValueError(f"{_STEP_ID}: primary_ipv4_priority must be a list")
    priority = [str(item).strip() for item in raw]
    if set(priority) != PRIORITY_STRATEGIES or len(priority) != len(PRIORITY_STRATEGIES):
        raise ValueError(
            f"{_STEP_ID}: primary_ipv4_priority must contain each of "
            f"{sorted(PRIORITY_STRATEGIES)} exactly once, got {priority!r}"
        )
    return priority


def _parse_primary_ipv4_custom_pattern(config: dict[str, Any], priority: list[str]) -> str:
    raw = config.get("primary_ipv4_custom_pattern") or ""
    pattern = str(raw).strip()
    if pattern and "custom_interface" in priority:
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ValueError(
                f"{_STEP_ID}: primary_ipv4_custom_pattern {pattern!r} is not valid regex: {exc}"
            ) from exc
    return pattern


async def _resolve_primary_ipv4(
    *,
    device: DeviceContext,
    interfaces: list[dict[str, Any]],
    update_primary_ipv4: bool,
    priority: list[str],
    custom_pattern: str,
) -> tuple[bool, str]:
    """Mutates ``interfaces`` in place (marks the chosen entry) and reports success.

    Returns ``(True, "")`` on success/nothing-to-check, or ``(False, message)`` when
    the device should be routed to the ``failure`` outcome.
    """
    if update_primary_ipv4:
        match = await select_primary_ipv4(interfaces, priority, custom_pattern)
        if match is None:
            return False, (
                f"No interface matched the configured primary_ipv4_priority {priority!r} "
                f"for device {device.name!r}"
            )
        mark_primary(interfaces, *match)
        return True, ""

    if not device.primary_ip4:
        return True, ""

    if not device_primary_ip_present(interfaces, device.primary_ip4):
        return False, (
            f"Device {device.name!r}'s known primary IPv4 {device.primary_ip4!r} is not "
            "configured on any parsed interface"
        )

    match = find_interface_for_ip(interfaces, device.primary_ip4)
    if match is not None:
        mark_primary(interfaces, *match)
    return True, ""


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    config_source = _parse_config_source(config)
    parsed_key = _parse_parsed_key(config)
    attributes = _parse_attributes(config)
    source_format = _parse_source_format(config)
    update_primary_ipv4 = parse_bool_flag(config, "update_primary_ipv4", step_id=_STEP_ID)
    priority = _parse_primary_ipv4_priority(config) if update_primary_ipv4 else []
    custom_pattern = (
        _parse_primary_ipv4_custom_pattern(config, priority) if update_primary_ipv4 else ""
    )

    if not source_format.supports_startup and config_source == "startup":
        raise ValueError(
            f"{_STEP_ID}: source_format {source_format.key!r} only supports config_source "
            f"'running' — {source_format.upstream_step} never captures show startup-config"
        )

    if "device" in attributes and source_format.device_fields is None:
        with_device_fields = sorted(k for k, f in SOURCE_FORMATS.items() if f.device_fields)
        raise ValueError(
            f"{_STEP_ID}: the 'device' attribute group is only available for source_format "
            f"{with_device_fields}, got {source_format.key!r}"
        )

    return _ParsedConfig(
        config_source=config_source,
        parsed_key=parsed_key,
        attributes=attributes,
        source_format=source_format,
        update_primary_ipv4=update_primary_ipv4,
        primary_ipv4_priority=priority,
        primary_ipv4_custom_pattern=custom_pattern,
    )


async def _process_device(
    device: DeviceContext, parsed: _ParsedConfig, parsed_entry: dict[str, Any]
) -> _DeviceResult:
    """Map one device's parsed entry; ``device`` is ``None`` when there is nothing to write."""
    fmt = parsed.source_format
    existing_bag = device.attribute_bags.get("nautobot")
    interfaces = fmt.interfaces(parsed_entry) if "interfaces" in parsed.attributes else []
    if interfaces and fmt.keep_existing_fields is not None:
        # The merge below replaces a whole interface: keep what earlier steps set on it.
        interfaces = fmt.keep_existing_fields(
            existing_bag.get("interfaces") if isinstance(existing_bag, dict) else None,
            interfaces,
        )
    device_fields = (
        fmt.device_fields(parsed_entry, device)
        if "device" in parsed.attributes and fmt.device_fields is not None
        else {}
    )
    if not interfaces and not device_fields:
        return _DeviceResult()

    note = None
    if "interfaces" in parsed.attributes and fmt.redundancy_note is not None:
        note = fmt.redundancy_note(device, parsed_entry)

    primary_ok, failure_message = True, ""
    if interfaces:
        primary_ok, failure_message = await _resolve_primary_ipv4(
            device=device,
            interfaces=interfaces,
            update_primary_ipv4=parsed.update_primary_ipv4,
            priority=parsed.primary_ipv4_priority,
            custom_pattern=parsed.primary_ipv4_custom_pattern,
        )
        if fmt.after_primary_ip is not None:
            fmt.after_primary_ip(interfaces)

    defaults = {**device_fields, **({"interfaces": interfaces} if interfaces else {})}
    merged_bag = merge_nautobot_defaults(existing_bag, defaults, overwrite=True)
    enriched = device.model_copy(
        update={
            "attribute_bags": {**device.attribute_bags, "nautobot": merged_bag},
            "capabilities": device.capabilities | {Capability.ATTRIBUTES},
        }
    )
    return _DeviceResult(
        device=enriched,
        interfaces_written=len(interfaces),
        note=note,
        primary_failure=None if primary_ok else failure_message,
    )


def _primary_ipv4_failed(device: DeviceContext, node_id: str, message: str) -> DeviceContext:
    return device.model_copy(
        update={
            "status": DeviceStatus.FAILED,
            "errors": [
                *device.errors,
                DeviceError(
                    node_id=node_id,
                    step_id=_STEP_ID,
                    code="primary_ipv4_not_found",
                    message=message,
                    failure=MISSING_DATA,
                ),
            ],
        }
    )


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions  # unused for this step

    parsed = _parse_config(config)
    fmt = parsed.source_format
    location = fmt.parsed_location(parsed.parsed_key, parsed.config_source)

    logger.info(
        "%s started run_id=%s node_id=%s source_format=%s config_source=%s parsed_key=%s "
        "attributes=%s update_primary_ipv4=%s devices=%d",
        _STEP_ID,
        log_run_id(run),
        node_id,
        fmt.key,
        parsed.config_source,
        parsed.parsed_key,
        sorted(parsed.attributes),
        parsed.update_primary_ipv4,
        len(context.devices),
    )

    if not parsed.attributes or not context.devices:
        logger.info("%s finished (no-op) run_id=%s", _STEP_ID, log_run_id(run))
        return [StepOutcome(name="success", context=context)]

    success_devices: dict[str, DeviceContext] = {}
    failed_devices: dict[str, DeviceContext] = {}
    no_data_devices: list[str] = []
    redundancy_notes: list[str] = []
    interfaces_written = 0
    primary_ipv4_failures = 0

    for device_id, device in context.devices.items():
        parsed_entry = fmt.select(device, parsed.parsed_key, parsed.config_source)
        result = (
            await _process_device(device, parsed, parsed_entry)
            if parsed_entry is not None
            else None
        )
        if result is None or result.device is None:
            no_data_devices.append(device_id)
            continue
        interfaces_written += result.interfaces_written
        if result.note:
            redundancy_notes.append(result.note)
        if result.primary_failure is None:
            success_devices[device_id] = result.device
        else:
            primary_ipv4_failures += 1
            failed_devices[device_id] = _primary_ipv4_failed(
                result.device, node_id, result.primary_failure
            )

    devices_with_data = len(success_devices) + len(failed_devices)
    if devices_with_data == 0:
        raise ValueError(
            f"{_STEP_ID}: no parsed config with usable data found at {location} on any device — "
            f"add a '{fmt.upstream_step}' step upstream with a matching output_key"
        )

    # A device without usable parsed data was not processed: it leaves through 'failure' instead
    # of passing as a success the next step would trust (C2R-01).
    for device_id in no_data_devices:
        failed_devices[device_id] = mark_device_failed(
            context.devices[device_id],
            node_id=node_id,
            step_id=_STEP_ID,
            code="no_parsed_data",
            failure=MISSING_DATA,
            message=f"no usable parsed config at {location} for this device",
        )

    logger.info(
        "%s finished run_id=%s devices_updated=%d interfaces_written=%d primary_ipv4_failures=%d",
        _STEP_ID,
        log_run_id(run),
        devices_with_data,
        interfaces_written,
        primary_ipv4_failures,
    )

    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": success_devices}),
            summary="; ".join(redundancy_notes) or None,
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
