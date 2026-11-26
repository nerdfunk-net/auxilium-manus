"""Pieces the interface mappers of ``config-to-attributes`` (Config to Attributes) share (W4-09).

Every mapper (cisco_config_parser, Genie running config, Batfish facts, Catalyst Center and ACI
details) starts an interface with ``base_interface`` and reads MTU and VLAN values with
``positive_int`` and ``vlan_id``; the two fact-dict mappers (Catalyst Center, ACI) also share
``fact_payload`` and ``clean_text``.
"""

from __future__ import annotations

from typing import Any

from workflow_steps.common.interface_values import infer_interface_type_from_name

DEFAULT_MANUFACTURER = "Cisco"
# The VLAN ids a device and Nautobot accept (0 and 4095 are reserved).
MIN_VLAN_ID = 1
MAX_VLAN_ID = 4094


def fact_payload(entry: dict[str, Any], fact: str) -> Any:
    """The ``parsed`` payload of one fact of a ``{"<fact>": {"parsed", "error"}}`` entry."""
    fact_entry = entry.get(fact) if isinstance(entry, dict) else None
    return fact_entry.get("parsed") if isinstance(fact_entry, dict) else None


def clean_text(value: Any) -> str | None:
    """``value`` as stripped text, or ``None`` when it is missing or blank."""
    stripped = str(value).strip() if value is not None else ""
    return stripped or None


def base_interface(name: str, *, enabled: bool, description: Any = None) -> dict[str, Any]:
    """The fields every mapper's interface starts with: name, ``Active``, the type inferred from
    the name, ``enabled`` and, when there is text, the stripped description."""
    iface: dict[str, Any] = {
        "name": name,
        "status": "Active",
        "type": infer_interface_type_from_name(name),
        "enabled": enabled,
    }
    text = clean_text(description)
    if text:
        iface["description"] = text
    return iface


def positive_int(value: Any) -> int | None:
    """An MTU (or any count) as an int above zero; a bool, text, a fraction or ``<= 0`` is none."""
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return value if isinstance(value, int) and value > 0 else None


def vlan_id(value: Any) -> int | None:
    """A VLAN id (an int or decimal text) within 1-4094, else ``None``: an id Nautobot would
    refuse is left out instead of failing the write."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text.isdecimal():
            return None
        value = int(text)
    if isinstance(value, int) and MIN_VLAN_ID <= value <= MAX_VLAN_ID:
        return value
    return None
