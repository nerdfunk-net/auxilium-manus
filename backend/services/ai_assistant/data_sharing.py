"""Opt-in data sharing (doc/ai_integration/AI_ASSISTANT.md §4).

Anything derived from devices or runs reaches the model only if the user switched the matching
class on. The check lives in the tool layer, not the UI: a tool asks the policy before it puts a
class B/C value in its result, and substitutes a ``not_shared`` marker otherwise so the model can
tell the user what to enable instead of failing silently.

Class B (inventory data) is split: device basics are the base switch, and three categories that
are more likely to carry sensitive values (addresses and serials, custom fields, config context)
each need their own switch **on top of** the base one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class DataClass(StrEnum):
    INVENTORY = "inventory_data"  # class B: device names, basic attributes, inventories
    ADDRESSES = "device_addresses"  # class B: IP addresses, serials, asset tags, interfaces
    CUSTOM_FIELDS = "custom_fields"  # class B
    CONFIG_CONTEXT = "config_context"  # class B
    CONTENT = "content_data"  # class C: command output, configs, errors, run logs


_SETTING_FOR: dict[DataClass, str] = {
    DataClass.INVENTORY: "Inventory and device attributes",
    DataClass.ADDRESSES: "Addresses and serial numbers",
    DataClass.CUSTOM_FIELDS: "Custom fields",
    DataClass.CONFIG_CONTEXT: "Config context",
    DataClass.CONTENT: "Run and device content",
}


@dataclass(frozen=True)
class SharingPolicy:
    """What the calling user has opted in to. The default shares nothing."""

    inventory: bool = False
    addresses: bool = False
    custom_fields: bool = False
    config_context: bool = False
    content: bool = False

    def allows(self, data_class: DataClass) -> bool:
        if data_class is DataClass.CONTENT:
            return self.content
        if data_class is DataClass.INVENTORY:
            return self.inventory
        # A category never works without the base inventory switch.
        flag = {
            DataClass.ADDRESSES: self.addresses,
            DataClass.CUSTOM_FIELDS: self.custom_fields,
            DataClass.CONFIG_CONTEXT: self.config_context,
        }[data_class]
        return self.inventory and flag

    def describe(self) -> str:
        """Short text for the system prompt."""
        parts = [
            label
            for label, on in (
                ("device basics", self.allows(DataClass.INVENTORY)),
                ("addresses and serials", self.allows(DataClass.ADDRESSES)),
                ("custom fields", self.allows(DataClass.CUSTOM_FIELDS)),
                ("config context", self.allows(DataClass.CONFIG_CONTEXT)),
                ("run and device content", self.allows(DataClass.CONTENT)),
            )
            if on
        ]
        return ", ".join(parts) if parts else "nothing"


def not_shared_marker(data_class: DataClass) -> dict[str, str]:
    """A value to put where withheld data would have been."""
    return {
        "not_shared": data_class.value,
        "message": (
            f"The user has not enabled '{_SETTING_FOR[data_class]}' in the assistant settings. "
            "Tell them to enable it if you need this, or answer without it."
        ),
    }


def gated(policy: SharingPolicy, data_class: DataClass, value: Any) -> Any:
    """``value`` if the class is shared, else the not-shared marker."""
    return value if policy.allows(data_class) else not_shared_marker(data_class)


# -- attribute classification -----------------------------------------------------------------

# Nautobot device attribute names by category. A name in none of these sets is never sent
# (see ``filter_nautobot_attributes``): new or unusual attributes are withheld by default.
BASIC_ATTRIBUTES = frozenset(
    {
        "id",
        "name",
        "status",
        "role",
        "platform",
        "device_type",
        "manufacturer",
        "location",
        "tags",
        "face",
        "position",
    }
)
ADDRESS_ATTRIBUTES = frozenset(
    {
        "hostname",
        "primary_ip4",
        "primary_ip6",
        "oob_ip",
        "ip_addresses",
        "interfaces",
        "serial",
        "asset_tag",
    }
)
CUSTOM_FIELD_ATTRIBUTES = frozenset({"custom_fields", "_custom_field_data", "computed_fields"})
CONFIG_CONTEXT_ATTRIBUTES = frozenset({"config_context", "local_config_context_data"})

_CATEGORY_OF: dict[str, DataClass] = {
    **dict.fromkeys(ADDRESS_ATTRIBUTES, DataClass.ADDRESSES),
    **dict.fromkeys(CUSTOM_FIELD_ATTRIBUTES, DataClass.CUSTOM_FIELDS),
    **dict.fromkeys(CONFIG_CONTEXT_ATTRIBUTES, DataClass.CONFIG_CONTEXT),
}


def attribute_class(name: str) -> DataClass | None:
    """Category an attribute needs, ``INVENTORY`` for basics, ``None`` if it is never shared."""
    if name in BASIC_ATTRIBUTES:
        return DataClass.INVENTORY
    return _CATEGORY_OF.get(name)


def filter_nautobot_attributes(
    policy: SharingPolicy, attributes: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Allow-list a Nautobot attribute bag. Returns ``(kept, withheld)`` where ``withheld`` maps
    each dropped name to the setting that would release it (or ``"never"``)."""
    kept: dict[str, Any] = {}
    withheld: dict[str, str] = {}
    for name, value in attributes.items():
        needed = attribute_class(name)
        if needed is None:
            withheld[name] = "never"
        elif policy.allows(needed):
            kept[name] = value
        else:
            withheld[name] = _SETTING_FOR[needed]
    return kept, withheld


def mask_run_attributes(policy: SharingPolicy, data: Any) -> Any:
    """Recursively replace values under address / custom-field / config-context keys.

    Run attribute bags hold arbitrary per-source keys, so this is a deny-list by key name rather
    than an allow-list: it covers the Nautobot-shaped keys wherever they are nested.
    """
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for key, value in data.items():
            needed = _CATEGORY_OF.get(key) if isinstance(key, str) else None
            if needed is not None and not policy.allows(needed):
                out[key] = {"not_shared": needed.value}
            else:
                out[key] = mask_run_attributes(policy, value)
        return out
    if isinstance(data, list):
        return [mask_run_attributes(policy, item) for item in data]
    return data


class DeviceLabeler:
    """Stable per-request device labels: real names when inventory data is shared, else
    ``device-1``, ``device-2`` ... so a failure can still be discussed per device."""

    def __init__(self, policy: SharingPolicy) -> None:
        self._share = policy.inventory
        self._labels: dict[str, str] = {}

    def seed(self, names: set[str]) -> None:
        """Number ``names`` in sorted order (names not yet labeled), independent of call order."""
        for name in sorted(names):
            self.label(name)

    def label(self, name: str) -> str:
        if self._share:
            return name
        return self._labels.setdefault(name, f"device-{len(self._labels) + 1}")

    def matches(self, name: str, wanted: str) -> bool:
        return wanted in (name, self.label(name)) if self._share else wanted == self.label(name)
