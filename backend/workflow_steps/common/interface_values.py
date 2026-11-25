"""Value normalisers for Nautobot interface fields (MAC, speed, duplex, MTU, type, CIDR)."""

from __future__ import annotations

import ipaddress
import logging
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

logger = logging.getLogger(__name__)


def strip_empty(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return value


# Lower-cased alphabetic prefix of an interface name -> Nautobot interface type slug. A convenience
# default for names written by Cisco-style platforms; the author can still override ``type``.
_INTERFACE_TYPE_BY_PREFIX: Mapping[str, str] = MappingProxyType(
    {
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
)
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
    cleaned = strip_empty(value)
    return cleaned if isinstance(cleaned, str) and cleaned != "none" else None


def lower_text(value: Any) -> str | None:
    cleaned = strip_empty(value)
    return cleaned.lower() if isinstance(cleaned, str) else None


# interface field -> normalizer. Every source (config rows, the bag, a parsed list) funnels its
# values through this table so they all accept and produce the same forms.
_FIELD_NORMALIZERS: Mapping[str, Any] = MappingProxyType(
    {
        "mac_address": normalize_mac,
        "speed": normalize_speed_kbps,
        "duplex": normalize_duplex,
        "mtu": normalize_mtu,
        "port_type": lower_text,
        "mode": lower_text,
        "vrf": _vrf_name,
    }
)


def apply_text_fields(iface: dict[str, Any], raw: dict[str, Any]) -> None:
    """Copy ``type`` (lower-cased) and ``description`` from ``raw``, text only.

    A list, dict or sealed-secret envelope in a cell is logged and left out: it must never be
    sent in a Nautobot request body.
    """
    for field in ("type", "description"):
        value = raw.get(field)
        if value is None:
            continue
        text = strip_empty(value) if isinstance(value, str) else None
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
