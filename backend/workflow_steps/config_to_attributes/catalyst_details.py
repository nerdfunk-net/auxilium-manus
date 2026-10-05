"""Build Nautobot attributes from Cisco Catalyst Center facts.

``get-catalyst-center-details`` writes ``device.parsed[parsed_key][<fact>] =
{"parsed": data | None, "error": str | None}`` for the facts ``device``, ``software``
and ``interfaces`` (models in ``models/catalyst_center_facts.py``). Unlike the other
source formats this is not a config tree, so the executor hands this module the whole
fact dict and it reads each fact's ``parsed`` payload.

Catalyst Center states no allowed-VLAN list for a trunk, so a trunk gets only its native
VLAN as ``untagged_vlan`` and never ``tagged_vlans``. Role, status and location cannot be
derived from the controller's record and are left to Set Default Attributes.
"""

from __future__ import annotations

from typing import Any

from workflow_steps.common.nautobot_interfaces import (
    cidr_from_ip_and_mask,
    infer_interface_type_from_name,
)

DEFAULT_MANUFACTURER = "Cisco"
_ACCESS = "access"
_TRUNK = "trunk"


def _fact_payload(entry: dict[str, Any], fact: str) -> Any:
    fact_entry = entry.get(fact) if isinstance(entry, dict) else None
    return fact_entry.get("parsed") if isinstance(fact_entry, dict) else None


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _vlan(value: Any) -> int | None:
    text = _text(value)
    if text is None or not text.isdecimal():
        return None
    vlan = int(text)
    return vlan or None


def _build_interface(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = _text(raw.get("name"))
    if name is None:
        return None

    iface: dict[str, Any] = {
        "name": name,
        "status": "Active",
        "type": infer_interface_type_from_name(name),
        "enabled": str(raw.get("admin_status") or "").strip().upper() == "UP",
    }

    description = _text(raw.get("description"))
    if description:
        iface["description"] = description

    mac_address = _text(raw.get("mac_address"))
    if mac_address:
        iface["mac_address"] = mac_address

    mtu = raw.get("mtu")
    if isinstance(mtu, int) and not isinstance(mtu, bool) and mtu:
        iface["mtu"] = mtu

    address = cidr_from_ip_and_mask(raw.get("ipv4_address"), raw.get("ipv4_mask"))
    if address:
        iface["ip_addresses"] = [{"address": address, "namespace": "Global"}]

    port_mode = (_text(raw.get("port_mode")) or "").lower()
    if port_mode == _ACCESS:
        iface["mode"] = _ACCESS
        untagged = _vlan(raw.get("vlan_id"))
    elif port_mode == _TRUNK:
        iface["mode"] = _TRUNK
        untagged = _vlan(raw.get("native_vlan_id"))
    else:
        untagged = None
    if untagged is not None:
        iface["untagged_vlan"] = untagged

    return iface


def build_interfaces_from_catalyst_details(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Interfaces from the ``interfaces`` fact; empty when it is missing or failed."""
    payload = _fact_payload(entry, "interfaces")
    if not isinstance(payload, list):
        return []
    built = (_build_interface(item) for item in payload if isinstance(item, dict))
    return [iface for iface in built if iface is not None]


def build_device_fields_from_catalyst_details(
    entry: dict[str, Any], vendor: str | None
) -> dict[str, Any]:
    """Device-level Nautobot fields from the ``device`` and ``software`` facts."""
    device = _fact_payload(entry, "device")
    software = _fact_payload(entry, "software")
    device = device if isinstance(device, dict) else {}
    software = software if isinstance(software, dict) else {}

    fields: dict[str, Any] = {}

    serial = _text(device.get("serial_number"))
    if serial:
        fields["serial"] = serial

    software_version = _text(software.get("software_version"))
    if software_version:
        fields["software_version"] = software_version

    platform = _text(software.get("software_type"))
    if platform:
        fields["platform"] = {"name": platform}

    model = _text(device.get("platform_id")) or _text(device.get("device_type"))
    if model:
        fields["device_type"] = {
            "model": model,
            "manufacturer": {"name": _text(vendor) or DEFAULT_MANUFACTURER},
        }

    return fields
