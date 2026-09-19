"""Executor for the config-to-attributes step."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import Capability, DeviceContext, StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from workflow_steps.common.attribute_defaults import merge_nautobot_defaults
from workflow_steps.common.nautobot_interfaces import (
    cidr_from_ip_and_mask,
    infer_interface_type_from_name,
)
from workflow_steps.config_to_attributes.batfish_facts import (
    build_interfaces_from_batfish_facts,
)
from workflow_steps.config_to_attributes.config import get_config
from workflow_steps.config_to_attributes.genie_running_config import (
    build_interfaces_from_genie_running_config,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "config-to-attributes"
_CONFIG_SOURCES = frozenset({"running", "startup"})
_SUPPORTED_ATTRIBUTES = frozenset({"interfaces"})
_VLAN_RANGE_RE = re.compile(r"^(\d+)-(\d+)$")
_SOURCE_FORMATS = frozenset({"cisco_config_parser", "genie", "batfish"})
_UPSTREAM_STEP_NAME = {
    "cisco_config_parser": "Parse Cisco Config",
    "genie": "Get & Parse Config",
    "batfish": "Extract Facts",
}
_STARTUP_UNSUPPORTED_FORMATS = frozenset({"genie", "batfish"})


def _parse_config_source(config: dict[str, Any]) -> str:
    raw = str(config.get("config_source") or get_config()["config_source"]).strip().lower()
    if raw not in _CONFIG_SOURCES:
        raise ValueError(
            f"{_STEP_ID}: config_source must be one of {sorted(_CONFIG_SOURCES)}, got {raw!r}"
        )
    return raw


def _parse_source_format(config: dict[str, Any]) -> str:
    raw = str(config.get("source_format") or get_config()["source_format"]).strip().lower()
    if raw not in _SOURCE_FORMATS:
        raise ValueError(
            f"{_STEP_ID}: source_format must be one of {sorted(_SOURCE_FORMATS)}, got {raw!r}"
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
    device: DeviceContext, parsed_key: str, config_source: str, source_format: str
) -> dict[str, Any] | None:
    """Resolve the parsed config model to read L3 interfaces from.

    ``parse-cisco-config``/``get-pyats-config`` always write ``{"running": ...,
    "startup": ...}`` at ``parsed[parsed_key]`` (the branch not parsed stays
    ``None``), so read the ``config_source`` sub-key directly. ``batfish-
    extract-facts`` writes a different, non-fatal shape instead — ``{"parsed":
    <node's facts or None>, "error": str | None}`` — with no running/startup
    distinction, so for that format read ``"parsed"`` regardless of
    ``config_source``.
    """
    entry = device.parsed.get(parsed_key)
    if not isinstance(entry, dict):
        return None
    if source_format == "batfish":
        nested = entry.get("parsed")
    else:
        nested = entry.get(config_source)
    return nested if isinstance(nested, dict) else None


def _is_enabled(children: Any) -> bool:
    if not isinstance(children, list):
        return True
    return not any(str(line).strip().lower() == "shutdown" for line in children)


def _build_interface(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None

    iface: dict[str, Any] = {
        "name": name,
        "status": "Active",
        "type": infer_interface_type_from_name(name),
        "enabled": _is_enabled(raw.get("children")),
    }

    description = str(raw.get("description") or "").strip()
    if description:
        iface["description"] = description

    ip_addresses: list[dict[str, Any]] = []
    primary_cidr = cidr_from_ip_and_mask(raw.get("ip_address"), raw.get("mask"))
    if primary_cidr:
        ip_addresses.append({"address": primary_cidr, "namespace": "Global", "is_primary": True})

    if raw.get("sec_ip_address") and raw.get("sec_mask") and raw.get("sec_subnet"):
        secondary_cidr = cidr_from_ip_and_mask(raw.get("sec_ip_address"), raw.get("sec_mask"))
        if secondary_cidr:
            ip_addresses.append(
                {"address": secondary_cidr, "namespace": "Global", "ip_role": "secondary"}
            )

    if ip_addresses:
        iface["ip_addresses"] = ip_addresses

    return iface


def _parse_vlan_list(raw: Any) -> list[int]:
    """Parse a comma-separated VLAN id/range string into a list of ints.

    E.g. ``"10,20,30-32"`` -> ``[10, 20, 30, 31, 32]``. Best-effort: the
    cisco_config_parser library's own regex only captures a single
    ``switchport trunk allowed vlan ...`` line via ``.search()``, so a
    continuation line like ``... vlan add 50`` is already invisible upstream
    of this function — this only parses whatever single line the library did
    capture.
    """
    if not raw:
        return []
    text = str(raw).strip()
    if not text:
        return []
    vlans: list[int] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        range_match = _VLAN_RANGE_RE.match(token)
        if range_match:
            start, end = int(range_match.group(1)), int(range_match.group(2))
            vlans.extend(range(start, end + 1))
        elif token.isdigit():
            vlans.append(int(token))
    return vlans


def _build_l2_access_interface(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None

    iface: dict[str, Any] = {
        "name": name,
        "status": "Active",
        "type": infer_interface_type_from_name(name),
        "enabled": _is_enabled(raw.get("children")),
        "mode": "access",
    }

    description = str(raw.get("description") or "").strip()
    if description:
        iface["description"] = description

    try:
        data_vlan = raw.get("data_vlan")
        if data_vlan not in (None, ""):
            iface["untagged_vlan"] = int(data_vlan)
    except (TypeError, ValueError):
        pass

    return iface


def _build_l2_trunk_interface(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = str(raw.get("name") or "").strip()
    if not name:
        return None

    iface: dict[str, Any] = {
        "name": name,
        "status": "Active",
        "type": infer_interface_type_from_name(name),
        "enabled": _is_enabled(raw.get("children")),
        "mode": "trunk",
    }

    description = str(raw.get("description") or "").strip()
    if description:
        iface["description"] = description

    tagged_vlans = _parse_vlan_list(raw.get("allowed_vlans"))
    if tagged_vlans:
        iface["tagged_vlans"] = tagged_vlans

    return iface


def _stub_interface(name: str, description: Any = None) -> dict[str, Any]:
    """A minimal interface entry for a name only known via ``port_channels``.

    Mitigates a cisco_config_parser gap: an interface whose only
    configuration is ``channel-group N mode X`` (no IP, no switchport
    command) — and a bundle interface with neither an IP nor a switchport
    command on it — is absent from ``l3_interfaces``, ``l2_access_interfaces``,
    and ``l2_trunk_interfaces`` alike; the library only records it inside
    ``port_channels[].members``/``port_channels[].name``. Its description and
    admin (shutdown) state cannot be recovered in this case — the library
    drops the whole interface stanza — so ``enabled`` defaults to ``True``.
    """
    iface: dict[str, Any] = {
        "name": name,
        "status": "Active",
        "type": infer_interface_type_from_name(name),
        "enabled": True,
    }
    desc = str(description or "").strip()
    if desc:
        iface["description"] = desc
    return iface


def _resolve_port_channel_name(port_channel: dict[str, Any]) -> str | None:
    name = str(port_channel.get("name") or "").strip()
    if name:
        return name
    po_id = str(port_channel.get("id") or "").strip()
    return f"Port-channel{po_id}" if po_id else None


def _apply_port_channels(interfaces: dict[str, dict[str, Any]], raw_port_channels: Any) -> None:
    """Fill LAG interfaces/members missing from the per-type sections above.

    Only fills gaps and adds ``lag`` — never overwrites ``mode``/
    ``tagged_vlans``/``untagged_vlan``/IP data an interface already picked up
    from ``l3_interfaces``/``l2_access_interfaces``/``l2_trunk_interfaces``.
    """
    if not isinstance(raw_port_channels, list):
        return
    for port_channel in raw_port_channels:
        if not isinstance(port_channel, dict):
            continue
        po_name = _resolve_port_channel_name(port_channel)
        if not po_name:
            continue
        if po_name not in interfaces:
            interfaces[po_name] = _stub_interface(po_name, port_channel.get("description"))

        members = port_channel.get("members")
        if not isinstance(members, list):
            continue
        for member in members:
            if not isinstance(member, dict):
                continue
            member_name = str(member.get("interface") or "").strip()
            if not member_name:
                continue
            if member_name not in interfaces:
                interfaces[member_name] = _stub_interface(member_name)
            interfaces[member_name]["lag"] = po_name


def _build_interfaces_cisco_config_parser(
    parsed_entry: dict[str, Any],
) -> list[dict[str, Any]]:
    interfaces: dict[str, dict[str, Any]] = {}

    for raw in parsed_entry.get("l3_interfaces") or []:
        if not isinstance(raw, dict):
            continue
        iface = _build_interface(raw)
        if iface is not None:
            interfaces[iface["name"]] = iface

    for raw in parsed_entry.get("l2_access_interfaces") or []:
        if not isinstance(raw, dict):
            continue
        iface = _build_l2_access_interface(raw)
        if iface is not None and iface["name"] not in interfaces:
            interfaces[iface["name"]] = iface

    for raw in parsed_entry.get("l2_trunk_interfaces") or []:
        if not isinstance(raw, dict):
            continue
        iface = _build_l2_trunk_interface(raw)
        if iface is not None and iface["name"] not in interfaces:
            interfaces[iface["name"]] = iface

    _apply_port_channels(interfaces, parsed_entry.get("port_channels"))

    return list(interfaces.values())


def _build_interfaces(parsed_entry: dict[str, Any], source_format: str) -> list[dict[str, Any]]:
    if source_format == "genie":
        return build_interfaces_from_genie_running_config(parsed_entry)
    if source_format == "batfish":
        return build_interfaces_from_batfish_facts(parsed_entry)
    return _build_interfaces_cisco_config_parser(parsed_entry)


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service  # unused for this step

    config_source = _parse_config_source(config)
    parsed_key = _parse_parsed_key(config)
    attributes = _parse_attributes(config)
    source_format = _parse_source_format(config)

    if source_format in _STARTUP_UNSUPPORTED_FORMATS and config_source == "startup":
        upstream_step = _UPSTREAM_STEP_NAME[source_format]
        raise ValueError(
            f"{_STEP_ID}: source_format {source_format!r} only supports config_source "
            f"'running' — {upstream_step} never captures show startup-config"
        )

    logger.info(
        "%s started run_id=%s node_id=%s source_format=%s config_source=%s parsed_key=%s "
        "attributes=%s devices=%d",
        _STEP_ID,
        run.id,
        node_id,
        source_format,
        config_source,
        parsed_key,
        sorted(attributes),
        len(context.devices),
    )

    if "interfaces" not in attributes or not context.devices:
        logger.info("%s finished (no-op) run_id=%s", _STEP_ID, run.id)
        return [StepOutcome(name="success", context=context)]

    updated_devices: dict[str, DeviceContext] = {}
    devices_with_data = 0
    interfaces_written = 0

    for device_id, device in context.devices.items():
        parsed_entry = _select_parsed_entry(device, parsed_key, config_source, source_format)
        if parsed_entry is None:
            continue

        interfaces = _build_interfaces(parsed_entry, source_format)
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
        upstream_step = _UPSTREAM_STEP_NAME[source_format]
        raise ValueError(
            f"{_STEP_ID}: no parsed config with interfaces found at "
            f"parsed.{parsed_key}.{config_source} on any device — add a '{upstream_step}' "
            "step upstream with a matching output_key"
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
