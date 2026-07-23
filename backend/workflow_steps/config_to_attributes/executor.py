"""Executor for the config-to-attributes step."""

from __future__ import annotations

import ipaddress
import logging
from typing import Any

from core.models.runs import WorkflowRun
from models.workflow_context import Capability, DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.attribute_defaults import merge_nautobot_defaults
from workflow_steps.config_to_attributes.config import get_config

logger = logging.getLogger(__name__)

_STEP_ID = "config-to-attributes"
_CONFIG_SOURCES = frozenset({"running", "startup"})
_SUPPORTED_ATTRIBUTES = frozenset({"layer3_interfaces"})


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


def _parse_attributes(config: dict[str, Any]) -> set[str]:
    raw = config["attributes"] if "attributes" in config else get_config()["attributes"]
    if not isinstance(raw, list):
        return set()
    return {str(item).strip() for item in raw if str(item).strip() in _SUPPORTED_ATTRIBUTES}


def _select_parsed_entry(
    device: DeviceContext, parsed_key: str, config_source: str
) -> dict[str, Any] | None:
    """Resolve the parsed Cisco config model to read L3 interfaces from.

    ``parse-cisco-config`` nests running/startup under sub-keys only when it was
    configured with ``config_source: both``; with a single source it writes the
    model directly at ``parsed[parsed_key]``. Handle both shapes.
    """
    entry = device.parsed.get(parsed_key)
    if not isinstance(entry, dict):
        return None
    nested = entry.get(config_source)
    if isinstance(nested, dict):
        return nested
    if "l3_interfaces" in entry:
        return entry
    return None


def _infer_interface_type(name: str) -> str:
    if name.startswith("Gigabit"):
        return "1000base-t"
    if name.startswith("Ethernet"):
        return "100base-tx"
    return "virtual"


def _is_enabled(children: Any) -> bool:
    if not isinstance(children, list):
        return True
    return not any(str(line).strip().lower() == "shutdown" for line in children)


def _to_cidr(ip_address: Any, mask: Any) -> str | None:
    ip_text = str(ip_address).strip() if ip_address else ""
    mask_text = str(mask).strip() if mask else ""
    if not ip_text or not mask_text:
        return None
    try:
        prefixlen = ipaddress.IPv4Network(f"0.0.0.0/{mask_text}", strict=False).prefixlen
    except ValueError:
        return None
    return f"{ip_text}/{prefixlen}"


def _build_interface(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None

    iface: dict[str, Any] = {
        "name": name,
        "status": "Active",
        "type": _infer_interface_type(name),
        "enabled": _is_enabled(raw.get("children")),
    }

    description = str(raw.get("description") or "").strip()
    if description:
        iface["description"] = description

    ip_addresses: list[dict[str, Any]] = []
    primary_cidr = _to_cidr(raw.get("ip_address"), raw.get("mask"))
    if primary_cidr:
        ip_addresses.append({"address": primary_cidr, "namespace": "Global"})

    if raw.get("sec_ip_address") and raw.get("sec_mask") and raw.get("sec_subnet"):
        secondary_cidr = _to_cidr(raw.get("sec_ip_address"), raw.get("sec_mask"))
        if secondary_cidr:
            ip_addresses.append({"address": secondary_cidr, "namespace": "Global"})

    if ip_addresses:
        iface["ip_addresses"] = ip_addresses

    return iface


def _build_layer3_interfaces(parsed_entry: dict[str, Any]) -> list[dict[str, Any]]:
    raw_interfaces = parsed_entry.get("l3_interfaces")
    if not isinstance(raw_interfaces, list):
        return []
    built: list[dict[str, Any]] = []
    for raw in raw_interfaces:
        if not isinstance(raw, dict):
            continue
        iface = _build_interface(raw)
        if iface is not None:
            built.append(iface)
    return built


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
) -> list[StepOutcome]:
    del artifact_service  # unused for this step

    config_source = _parse_config_source(config)
    parsed_key = _parse_parsed_key(config)
    attributes = _parse_attributes(config)

    logger.info(
        "%s started run_id=%s node_id=%s config_source=%s parsed_key=%s attributes=%s "
        "devices=%d",
        _STEP_ID,
        run.id,
        node_id,
        config_source,
        parsed_key,
        sorted(attributes),
        len(context.devices),
    )

    if "layer3_interfaces" not in attributes or not context.devices:
        logger.info("%s finished (no-op) run_id=%s", _STEP_ID, run.id)
        return [StepOutcome(name="success", context=context)]

    updated_devices: dict[str, DeviceContext] = {}
    devices_with_data = 0
    interfaces_written = 0

    for device_id, device in context.devices.items():
        parsed_entry = _select_parsed_entry(device, parsed_key, config_source)
        if parsed_entry is None:
            continue

        interfaces = _build_layer3_interfaces(parsed_entry)
        if not interfaces:
            continue

        devices_with_data += 1
        interfaces_written += len(interfaces)

        existing_bag = device.attribute_bags.get("nautobot")
        merged_bag = merge_nautobot_defaults(
            existing_bag, {"interfaces": interfaces}, overwrite=True
        )
        updated_devices[device_id] = device.model_copy(
            update={
                "attribute_bags": {**device.attribute_bags, "nautobot": merged_bag},
                "capabilities": device.capabilities | {Capability.ATTRIBUTES},
            }
        )

    if devices_with_data == 0:
        raise ValueError(
            f"{_STEP_ID}: no parsed Cisco config with l3_interfaces found at "
            f"parsed.{parsed_key} ({config_source}) on any device — add a 'Parse Cisco "
            f"Config' step upstream with a matching output_key"
        )

    for device_id, device in context.devices.items():
        if device_id not in updated_devices:
            updated_devices[device_id] = device

    logger.info(
        "%s finished run_id=%s devices_updated=%d interfaces_written=%d",
        _STEP_ID,
        run.id,
        devices_with_data,
        interfaces_written,
    )

    new_context = context.model_copy(update={"devices": updated_devices})
    return [StepOutcome(name="success", context=new_context)]
