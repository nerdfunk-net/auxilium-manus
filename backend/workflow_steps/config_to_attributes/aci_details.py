"""Build Nautobot attributes from Cisco ACI facts.

``get-aci-details`` writes ``device.parsed[parsed_key][<fact>] = {"parsed": data | None,
"error": str | None}`` for the facts ``device``, ``software`` and ``interfaces`` (models in
``models/aci_facts.py``). Like the Catalyst Center format this is not a config tree, so the executor
hands this module the whole fact dict and it reads each fact's ``parsed`` payload.

What is deliberately **not** mapped:

- VLANs (``mode``, ``untagged_vlan``, ``tagged_vlans``): an ACI port carries leaf-local platform
  VLAN ids that are assigned per EPG encapsulation, not VLANs of the data centre, so writing them to
  Nautobot would invent VLANs.
- Role, status and location cannot be derived from the APIC's record (the leaf/spine role is not a
  Nautobot role name); they are left to Set Default Attributes.
- The manufacturer is always ``Cisco`` (the APIC's vendor string is ``Cisco Systems, Inc``).
- The interface ``type`` comes from the interface kind, then from the *known* speed; a port whose
  speed is ``inherit`` (a policy decides) is ``other``, never a guess.
- The ``duplex`` is never sent: Nautobot accepts it on copper twisted-pair types only and the APIC
  speed does not say the media (100M and 1G ports are therefore ``other`` too).
- The TEP loopback address (``lo0``) is dropped after primary-IP selection unless it was chosen
  (``drop_unselected_tep_addresses``).
- SVI addresses: every leaf of a bridge domain carries the same anycast gateway address.
"""

from __future__ import annotations

from typing import Any

from workflow_steps.common.nautobot_interfaces import (
    apply_normalized_fields,
    normalize_speed_kbps,
)

DEFAULT_MANUFACTURER = "Cisco"
PLATFORM_NAME = "Cisco ACI"

# Nautobot interface type slug by speed in Kbps (the unit ``normalize_speed_kbps`` returns).
# 100M and 1G are left out on purpose: they are copper or a fibre SFP and the APIC speed does not
# say which, so those ports stay ``other`` rather than carry a wrong media type.
_TYPE_BY_SPEED_KBPS: dict[int, str] = {
    10_000_000: "10gbase-x-sfpp",
    25_000_000: "25gbase-x-sfp28",
    40_000_000: "40gbase-x-qsfpp",
    100_000_000: "100gbase-x-qsfp28",
}
# The management port (``mgmt0``) is an RJ-45 copper port, so its media is known.
_MANAGEMENT_TYPE_BY_SPEED_KBPS: dict[int, str] = {100_000: "100base-tx", 1_000_000: "1000base-t"}
_TYPE_BY_KIND = {"port_channel": "lag", "loopback": "virtual", "svi": "virtual"}
_SPEED_KINDS = frozenset({"physical", "management"})
# The fabric TEP: its address is fabric-internal, so it is not exported (see below).
TEP_INTERFACE = "lo0"
# Every leaf of a bridge domain carries the same anycast gateway address, so mapping an SVI
# address would try to create one Nautobot address from several devices.
_UNMAPPED_ADDRESS_KINDS = frozenset({"svi"})


def _fact_payload(entry: dict[str, Any], fact: str) -> Any:
    fact_entry = entry.get(fact) if isinstance(entry, dict) else None
    return fact_entry.get("parsed") if isinstance(fact_entry, dict) else None


def _text(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _interface_type(kind: str | None, speed_kbps: int | None) -> str:
    if kind in _TYPE_BY_KIND:
        return _TYPE_BY_KIND[kind]
    if kind == "management" and speed_kbps in _MANAGEMENT_TYPE_BY_SPEED_KBPS:
        return _MANAGEMENT_TYPE_BY_SPEED_KBPS[speed_kbps]
    if kind in _SPEED_KINDS and speed_kbps is not None:
        return _TYPE_BY_SPEED_KBPS.get(speed_kbps, "other")
    return "other"


def _build_interface(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = _text(raw.get("name"))
    if name is None:
        return None
    kind = _text(raw.get("kind"))
    # The operational speed is what the port runs at; the configured one only says what it may do.
    speed_text = _text(raw.get("oper_speed")) or _text(raw.get("speed"))

    iface: dict[str, Any] = {
        "name": name,
        "status": "Active",
        "enabled": str(raw.get("admin_status") or "").strip().lower() == "up",
    }
    description = _text(raw.get("description"))
    if description:
        iface["description"] = description

    apply_normalized_fields(
        iface,
        {
            "mac_address": raw.get("mac_address"),
            "mtu": raw.get("mtu"),
            "speed": speed_text,
        },
    )
    iface["type"] = _interface_type(kind, iface.get("speed") or normalize_speed_kbps(speed_text))

    addresses = [
        {"address": address, "namespace": "Global"}
        for item in raw.get("ipv4_addresses") or []
        if kind not in _UNMAPPED_ADDRESS_KINDS
        and isinstance(item, dict)
        and (address := _text(item.get("address")))
    ]
    if addresses:
        iface["ip_addresses"] = addresses

    channel = _text(raw.get("port_channel"))
    if channel:
        iface["lag"] = channel
    return iface


def build_interfaces_from_aci_details(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """Interfaces from the ``interfaces`` fact; empty when it is missing or failed."""
    payload = _fact_payload(entry, "interfaces")
    if not isinstance(payload, list):
        return []
    built = (_build_interface(item) for item in payload if isinstance(item, dict))
    return [iface for iface in built if iface is not None]


def build_device_fields_from_aci_details(entry: dict[str, Any]) -> dict[str, Any]:
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
    if device or software:
        fields["platform"] = {"name": PLATFORM_NAME}
    model = _text(device.get("model"))
    if model:
        fields["device_type"] = {"model": model, "manufacturer": {"name": DEFAULT_MANUFACTURER}}
    return fields


def drop_unselected_tep_addresses(interfaces: list[dict[str, Any]]) -> None:
    """Remove the fabric TEP address from ``lo0`` unless primary-IP selection picked it.

    The TEP is fabric-internal and not a management address; the user opts in by naming the
    interface in ``primary_ipv4_custom_pattern``, which marks the address as primary. Mutates
    ``interfaces`` in place (they are this step's own fresh copies).
    """
    for iface in interfaces:
        if iface.get("name") != TEP_INTERFACE:
            continue
        kept = [a for a in iface.get("ip_addresses") or [] if a.get("is_primary")]
        if kept:
            iface["ip_addresses"] = kept
        else:
            iface.pop("ip_addresses", None)


def keep_unmapped_interface_fields(
    existing: Any, built: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """``built`` interfaces, each completed with the fields an earlier step already set.

    This mapper leaves out VLANs, port mode and SVI addresses, and the later merge replaces a
    whole interface. A field the mapper does not produce therefore keeps its existing value; a
    field it does produce wins. Interfaces that exist only in ``existing`` are not touched here.
    """
    by_name = {
        str(item.get("name")): item
        for item in existing or []
        if isinstance(item, dict) and item.get("name")
    }
    return [{**by_name.get(str(iface["name"]), {}), **iface} for iface in built]
