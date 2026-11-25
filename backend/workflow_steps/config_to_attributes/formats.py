"""The five source formats of config-to-attributes as one table.

Every format ends in the same output (a list of interface dicts and, for some, device fields
merged into the ``nautobot`` attribute bag); only where the upstream data sits and how it is
mapped differ. A new format is one entry in ``SOURCE_FORMATS``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from models.workflow_context import DeviceContext
from workflow_steps.config_to_attributes.aci_details import (
    build_device_fields_from_aci_details,
    build_interfaces_from_aci_details,
    drop_unselected_tep_addresses,
    keep_unmapped_interface_fields,
)
from workflow_steps.config_to_attributes.batfish_facts import (
    build_interfaces_from_batfish_facts,
    interfaces_missing_hsrp_details,
)
from workflow_steps.config_to_attributes.catalyst_details import (
    build_device_fields_from_catalyst_details,
    build_interfaces_from_catalyst_details,
)
from workflow_steps.config_to_attributes.cisco_config import build_interfaces_from_cisco_config
from workflow_steps.config_to_attributes.genie_redundancy import (
    interfaces_with_unsupported_redundancy,
)
from workflow_steps.config_to_attributes.genie_running_config import (
    build_interfaces_from_genie_running_config,
)

ParsedEntry = dict[str, Any]


@dataclass(frozen=True)
class SourceFormat:
    """How one upstream step's parsed data becomes Nautobot interfaces and device fields."""

    key: str
    upstream_step: str
    interfaces: Callable[[ParsedEntry], list[dict[str, Any]]]
    # ``True``: the upstream step writes one ``{"parsed", "error"}`` entry per fact, so the
    # builders get the whole fact dict instead of one ``running``/``startup`` sub-entry.
    fact_dict: bool = False
    # Sub-key of the parsed entry to read when it is not the ``config_source``.
    nested_key: str | None = None
    supports_startup: bool = True
    device_fields: Callable[[ParsedEntry, DeviceContext], dict[str, Any]] | None = None
    redundancy_note: Callable[[DeviceContext, ParsedEntry], str | None] | None = None
    # Hooks of the ACI format: keep what earlier steps set on an interface before the merge
    # replaces it, and drop the fabric TEP address after primary-IP selection.
    keep_existing_fields: (
        Callable[[Any, list[dict[str, Any]]], list[dict[str, Any]]] | None
    ) = None
    after_primary_ip: Callable[[list[dict[str, Any]]], None] | None = None

    def select(
        self, device: DeviceContext, parsed_key: str, config_source: str
    ) -> ParsedEntry | None:
        """The parsed entry to read interfaces from, or ``None`` when the device has none."""
        entry = device.parsed.get(parsed_key)
        if not isinstance(entry, dict):
            return None
        if self.fact_dict:
            return entry
        nested = entry.get(self.nested_key or config_source)
        return nested if isinstance(nested, dict) else None

    def parsed_location(self, parsed_key: str, config_source: str) -> str:
        """Where the upstream data is, for messages."""
        if self.fact_dict:
            return f"parsed.{parsed_key}.<fact>"
        return f"parsed.{parsed_key}.{config_source}"


def _catalyst_vendor(device: DeviceContext) -> str | None:
    """Vendor recorded in the raw Catalyst Center inventory bag, if any."""
    bag = device.attribute_bags.get("catalyst_center")
    vendor = bag.get("vendor") if isinstance(bag, dict) else None
    return vendor if isinstance(vendor, str) else None


def _genie_note(device: DeviceContext, entry: ParsedEntry) -> str | None:
    names = interfaces_with_unsupported_redundancy(entry)
    if not names:
        return None
    return (
        f"{device.name}: VRRP configuration in the 'address-family' form on "
        f"{', '.join(names)} is not supported, no redundancy group was built"
    )


def _batfish_note(device: DeviceContext, entry: ParsedEntry) -> str | None:
    names = interfaces_missing_hsrp_details(entry)
    if not names:
        return None
    reason = str(entry.get("HSRP_Details_Error") or "no HSRP details in the facts")
    return f"{device.name}: HSRP groups on {', '.join(names)} were not built ({reason})"


SOURCE_FORMATS: dict[str, SourceFormat] = {
    fmt.key: fmt
    for fmt in (
        SourceFormat(
            key="cisco_config_parser",
            upstream_step="Parse Cisco Config",
            interfaces=build_interfaces_from_cisco_config,
        ),
        SourceFormat(
            key="genie",
            upstream_step="Get & Parse Config",
            interfaces=build_interfaces_from_genie_running_config,
            supports_startup=False,
            redundancy_note=_genie_note,
        ),
        SourceFormat(
            key="batfish",
            upstream_step="Extract Facts",
            interfaces=build_interfaces_from_batfish_facts,
            nested_key="parsed",
            supports_startup=False,
            redundancy_note=_batfish_note,
        ),
        SourceFormat(
            key="catalyst_details",
            upstream_step="Get Details from Catalyst Center",
            interfaces=build_interfaces_from_catalyst_details,
            fact_dict=True,
            supports_startup=False,
            device_fields=lambda entry, device: build_device_fields_from_catalyst_details(
                entry, _catalyst_vendor(device)
            ),
        ),
        SourceFormat(
            key="aci_details",
            upstream_step="Get Details from ACI",
            interfaces=build_interfaces_from_aci_details,
            fact_dict=True,
            supports_startup=False,
            device_fields=lambda entry, _device: build_device_fields_from_aci_details(entry),
            keep_existing_fields=keep_unmapped_interface_fields,
            after_primary_ip=drop_unselected_tep_addresses,
        ),
    )
}
