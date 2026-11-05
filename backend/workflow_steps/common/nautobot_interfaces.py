"""Build the interface-list payload shared by Nautobot device write steps."""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import Any

from services.nautobot.devices.interface_workflow.payload import namespace_name

logger = logging.getLogger(__name__)


def _strip_empty(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


# Lower-cased alphabetic prefix of an interface name -> Nautobot interface type slug. A convenience
# default for names written by Cisco-style platforms; the author can still override ``type``.
_INTERFACE_TYPE_BY_PREFIX: dict[str, str] = {
    "port-channel": "lag",
    "po": "lag",
    "bundle-ether": "lag",
    "ae": "lag",
    "vlan": "virtual",
    "loopback": "virtual",
    "lo": "virtual",
    "tunnel": "virtual",
    "null": "virtual",
    "nve": "virtual",
    "fastethernet": "100base-tx",
    "fa": "100base-tx",
    "gigabitethernet": "1000base-t",
    "gigabit": "1000base-t",
    "gi": "1000base-t",
    "ge": "1000base-t",
    "ethernet": "1000base-t",
    "mgmt": "1000base-t",
    "management": "1000base-t",
    "tengigabitethernet": "10gbase-x-sfpp",
    "tengige": "10gbase-x-sfpp",
    "te": "10gbase-x-sfpp",
    "xe": "10gbase-x-sfpp",
    "twentyfivegige": "25gbase-x-sfp28",
    "twe": "25gbase-x-sfp28",
    "fortygigabitethernet": "40gbase-x-qsfpp",
    "fortygige": "40gbase-x-qsfpp",
    "fo": "40gbase-x-qsfpp",
    "hundredgige": "100gbase-x-qsfp28",
    "hu": "100gbase-x-qsfp28",
}
_ALPHA_PREFIX = re.compile(r"[A-Za-z][A-Za-z-]*")


def infer_interface_type_from_name(name: str) -> str:
    """Guess a Nautobot interface type slug from an interface name.

    An unknown name is ``other``, not ``virtual``: Nautobot refuses cables on virtual interfaces.
    """
    match = _ALPHA_PREFIX.match(name.strip())
    prefix = match.group(0).lower().rstrip("-") if match else ""
    return _INTERFACE_TYPE_BY_PREFIX.get(prefix, "other")


# --- Field normalizers -------------------------------------------------------------------------
# Device output (TextFSM, hand-typed config, the attribute bag) spells the same value many ways.
# Each normalizer returns the Nautobot form, or None for "blank or not understood" (the caller
# then leaves the field out, so an existing Nautobot value is never overwritten with junk).

_MAC_DIGITS = re.compile(r"^[0-9a-f]{12}$")
_SPEED = re.compile(r"^(\d+(?:\.\d+)?)\s*([kmgt]?)(?:bit|b)?(?:/s|ps)?$", re.IGNORECASE)
_SPEED_FACTOR_KBPS = {"": 1, "k": 1, "m": 1_000, "g": 1_000_000, "t": 1_000_000_000}
_DUPLEX_VALUES = ("full", "half", "auto")


def normalize_mac(value: Any) -> str | None:
    """``aabb.cc00.0100`` / ``aa-bb-...`` / ``aabbcc000100`` -> ``AA:BB:CC:00:01:00``."""
    if not isinstance(value, str):
        return None
    digits = re.sub(r"[.:\-\s]", "", value).lower()
    if not _MAC_DIGITS.match(digits):
        return None
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2)).upper()


def normalize_speed_kbps(value: Any) -> int | None:
    """Speed in **Kbps** (Nautobot's unit). ``"10000 Kbit"``, ``"1Gb/s"`` or an int.

    A bare number is already Kbps. ``auto``, blank or unparsable gives None.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if not isinstance(value, str):
        return None
    match = _SPEED.match(value.strip())
    if not match:
        return None
    kbps = int(float(match.group(1)) * _SPEED_FACTOR_KBPS[match.group(2).lower()])
    return kbps if kbps > 0 else None


def normalize_duplex(value: Any) -> str | None:
    """``Full-duplex`` / ``a-full`` / ``HALF`` / ``auto`` -> ``full|half|auto``."""
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    for candidate in _DUPLEX_VALUES:
        if candidate in text:
            return candidate
    return None


def normalize_mtu(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isdigit():
        number = int(value.strip())
        return number if number > 0 else None
    return None


def _vrf_name(value: Any) -> str | None:
    """A VRF given as a name/UUID or as a Nautobot object (``{"name": ...}`` / ``{"id": ...}``)."""
    if isinstance(value, dict):
        value = value.get("name") or value.get("id")
    cleaned = _strip_empty(value)
    return cleaned if isinstance(cleaned, str) and cleaned != "none" else None


def _lower_text(value: Any) -> str | None:
    cleaned = _strip_empty(value)
    return cleaned.lower() if isinstance(cleaned, str) else None


# interface field -> normalizer. Every source (config rows, the bag, a parsed list) funnels its
# values through this table so they all accept and produce the same forms.
_FIELD_NORMALIZERS: dict[str, Any] = {
    "mac_address": normalize_mac,
    "speed": normalize_speed_kbps,
    "duplex": normalize_duplex,
    "mtu": normalize_mtu,
    "port_type": _lower_text,
    "mode": _lower_text,
    "vrf": _vrf_name,
}


def apply_text_fields(iface: dict[str, Any], raw: dict[str, Any]) -> None:
    """Copy ``type`` (lower-cased) and ``description`` from ``raw``, text only.

    A list, dict or sealed-secret envelope in a cell is logged and left out: it must never be
    sent in a Nautobot request body.
    """
    for field in ("type", "description"):
        value = raw.get(field)
        if value is None:
            continue
        text = _strip_empty(value) if isinstance(value, str) else None
        if text is None:
            if not (isinstance(value, str) and not value.strip()):
                logger.warning(
                    "Interface %r: %s value is not text - field left out", iface.get("name"), field
                )
            continue
        iface[field] = text.lower() if field == "type" else text


def apply_normalized_fields(
    iface: dict[str, Any], raw: dict[str, Any], fields: tuple[str, ...] | None = None
) -> None:
    """Copy the normalizable fields of ``raw`` into ``iface``.

    A non-blank value the normalizer cannot understand is logged and left out.
    """
    for field in fields or tuple(_FIELD_NORMALIZERS):
        if field not in raw:
            continue
        value = raw[field]
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        normalized = _FIELD_NORMALIZERS[field](value)
        if normalized is None:
            logger.warning(
                "Interface %r: %s value %r not understood - field left out",
                iface.get("name"),
                field,
                value,
            )
            continue
        iface[field] = normalized


def cidr_from_ip_and_mask(ip_address: Any, mask: Any) -> str | None:
    """Combine a dotted IP and dotted subnet mask into a CIDR string."""
    ip_text = str(ip_address).strip() if ip_address else ""
    mask_text = str(mask).strip() if mask else ""
    if not ip_text or not mask_text:
        return None
    try:
        prefixlen = ipaddress.IPv4Network(f"0.0.0.0/{mask_text}", strict=False).prefixlen
    except ValueError:
        return None
    return f"{ip_text}/{prefixlen}"


def build_interfaces_from_config(config: dict[str, Any], *, step_id: str) -> list[dict[str, Any]]:
    """Extract and clean the ``interfaces`` list from step config.

    Raises ``ValueError`` (prefixed with ``step_id``) when ``interfaces`` is present
    but not a list.
    """
    raw_interfaces = config.get("interfaces") or []
    if not isinstance(raw_interfaces, list):
        raise ValueError(f"{step_id}: interfaces must be a list")

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
            "ip_role",
            "untagged_vlan",
            "lag",
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
        apply_normalized_fields(iface, item)
        tagged_vlans = item.get("tagged_vlans")
        if isinstance(tagged_vlans, list):
            cleaned_tagged_vlans = [v for v in tagged_vlans if v not in (None, "")]
            if cleaned_tagged_vlans:
                iface["tagged_vlans"] = cleaned_tagged_vlans
        if item.get("is_primary_ipv4"):
            iface["is_primary_ipv4"] = True
        interfaces.append(iface)
    return interfaces


def normalize_interfaces(
    interfaces: list[dict[str, Any]],
    default_prefix_length: str,
) -> list[dict[str, Any]]:
    """Append ``default_prefix_length`` to any bare (no ``/nn``) interface IP address."""
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


def _ip_namespace_name(ip_item: dict[str, Any]) -> str | None:
    """Namespace of a bag IP: ``parent.namespace.name`` (Nautobot shape), else ``namespace``."""
    parent = ip_item.get("parent")
    namespace = parent.get("namespace") if isinstance(parent, dict) else None
    if isinstance(namespace, dict):
        name = _strip_empty(namespace.get("name"))
        if isinstance(name, str):
            return name
    return namespace_name(ip_item.get("namespace"))


def interfaces_from_nautobot_bag(
    bag: dict[str, Any] | None, *, default_prefix_length: str
) -> list[dict[str, Any]]:
    """Build the interfaces payload directly from a device's nautobot attribute bag.

    Unlike ``build_interfaces_from_config`` (a hand-typed config list — a fixed
    number of interfaces, one IP each, declared in advance), this reads however many
    interfaces the bag actually has, each with however many IPs it has. The plural
    ``ip_addresses`` shape is passed straight through to
    ``InterfaceManagerService.update_device_interfaces``, which already supports
    multiple IPs per interface (see ``interface.get("ip_addresses", [])`` there) —
    no new backend service support was needed for this.
    """
    if not isinstance(bag, dict):
        return []
    raw_interfaces = bag.get("interfaces")
    if not isinstance(raw_interfaces, list):
        return []

    suffix = (
        default_prefix_length
        if default_prefix_length.startswith("/")
        else f"/{default_prefix_length.lstrip('/')}"
    )

    interfaces: list[dict[str, Any]] = []
    for item in raw_interfaces:
        if not isinstance(item, dict):
            continue
        name = _strip_empty(item.get("name"))
        if not name:
            continue

        iface: dict[str, Any] = {"name": name}

        iface_type = _strip_empty(item.get("type"))
        if iface_type:
            iface["type"] = iface_type

        description = _strip_empty(item.get("description"))
        if description:
            iface["description"] = description

        status = item.get("status")
        status_name = _strip_empty(status.get("name") if isinstance(status, dict) else status)
        if status_name:
            iface["status"] = status_name

        enabled = item.get("enabled")
        if isinstance(enabled, bool):
            iface["enabled"] = enabled

        # mac_address, mtu, mode, port_type, speed, duplex, vrf (normalized to Nautobot's forms)
        apply_normalized_fields(iface, item)

        # untagged_vlan may be a pre-resolved Nautobot VLAN UUID or a raw vid
        # (int) — resolution/creation happens downstream, at Nautobot write
        # time, so it is passed through as-is here.
        untagged_vlan = item.get("untagged_vlan")
        if untagged_vlan and untagged_vlan != "none":
            iface["untagged_vlan"] = untagged_vlan

        # lag may be a pre-resolved Nautobot interface UUID or a raw
        # interface name (e.g. "Port-channel10") — resolved downstream,
        # at Nautobot write time, against the same device's interfaces.
        lag = item.get("lag")
        if lag and lag != "none":
            iface["lag"] = lag

        # tagged_vlans entries may be pre-resolved Nautobot VLAN UUIDs or raw
        # vids (int) — resolved/created downstream, at Nautobot write time,
        # same as untagged_vlan above.
        tagged_vlans = item.get("tagged_vlans")
        if isinstance(tagged_vlans, list):
            cleaned_tagged_vlans = [v for v in tagged_vlans if v not in (None, "", "none")]
            if cleaned_tagged_vlans:
                iface["tagged_vlans"] = cleaned_tagged_vlans

        raw_ip_addresses = item.get("ip_addresses")
        if isinstance(raw_ip_addresses, list):
            addresses: list[dict[str, Any]] = []
            for ip_item in raw_ip_addresses:
                is_dict = isinstance(ip_item, dict)
                address = _strip_empty(ip_item.get("address") if is_dict else ip_item)
                if not address:
                    continue
                if "/" not in address:
                    address = f"{address}{suffix}"
                namespace = (_ip_namespace_name(ip_item) if is_dict else None) or "Global"
                entry: dict[str, Any] = {"address": address, "namespace": namespace}
                if is_dict:
                    ip_role = _strip_empty(ip_item.get("ip_role"))
                    if ip_role and ip_role != "none":
                        entry["ip_role"] = ip_role
                    if ip_item.get("is_primary"):
                        entry["is_primary"] = True
                addresses.append(entry)
            if addresses:
                iface["ip_addresses"] = addresses

        interfaces.append(iface)

    return interfaces


NEW_TYPE_MODES = frozenset({"none", "infer", "fixed"})


def interfaces_from_parsed_list(
    rows: Any,
    field_map: dict[str, str],
    *,
    fixed_values: dict[str, Any] | None = None,
    new_type_mode: str = "none",
    new_type_value: str = "",
) -> list[dict[str, Any]]:
    """Build the interfaces payload from a parsed list of dicts (e.g. TextFSM ``show interfaces``).

    ``field_map`` maps an interface field (``name``, ``mac_address``, ``mtu``, ``speed``,
    ``duplex``, ``port_type``, ``mode``, ``vrf``, ``type``, ``description``) to the column that
    holds it. ``name`` is required. ``fixed_values`` sets a field to the same value on every
    row (for example ``type`` - TextFSM output has no Nautobot interface type, but a new
    interface cannot be created without one). A column cell that is blank leaves that field out,
    so an existing Nautobot value is not wiped. Rows without a name, and non-dict rows, are skipped.

    ``new_type_mode`` sets ``type_if_new``, a type used ONLY when the interface does not exist yet
    (the interface workflow ignores it for an existing interface, unlike ``type``, which is always
    patched): ``none`` adds nothing, ``infer`` guesses it from the interface name
    (``infer_interface_type_from_name``), ``fixed`` uses ``new_type_value`` for every row.
    """
    if new_type_mode not in NEW_TYPE_MODES:
        raise ValueError(f"parsed list: new_type_mode must be one of {sorted(NEW_TYPE_MODES)}")
    fixed_new_type = _lower_text(new_type_value) if new_type_mode == "fixed" else None
    if new_type_mode == "fixed" and not fixed_new_type:
        raise ValueError("parsed list: new_type_mode 'fixed' needs a type value")

    name_column = _strip_empty(field_map.get("name"))
    if not name_column:
        raise ValueError("parsed list: the 'name' column mapping is required")
    if not isinstance(rows, list):
        raise ValueError("parsed list: the attribute path must resolve to a list of objects")

    interfaces: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = _strip_empty(row.get(name_column))
        if not isinstance(name, str):
            continue
        source: dict[str, Any] = dict(fixed_values or {})
        for field, column in field_map.items():
            if field == "name" or not column or column not in row:
                continue
            cell = row[column]
            # A blank cell leaves the fixed value (or nothing) in place; it never erases it.
            if cell is None or (isinstance(cell, str) and not cell.strip()):
                continue
            source[field] = cell
        iface: dict[str, Any] = {"name": name}
        apply_text_fields(iface, source)
        apply_normalized_fields(iface, source)
        if new_type_mode == "infer":
            iface["type_if_new"] = infer_interface_type_from_name(name)
        elif fixed_new_type:
            iface["type_if_new"] = fixed_new_type
        interfaces.append(iface)
    return interfaces
