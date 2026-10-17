"""Mutable accumulator for one ``update_device_interfaces`` call."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from services.nautobot.devices.types import InterfaceUpdateResult


@dataclass
class InterfaceUpdateState:
    created_interfaces: list[str] = dataclass_field(default_factory=list)
    updated_interfaces: list[str] = dataclass_field(default_factory=list)
    failed_interfaces: list[str] = dataclass_field(default_factory=list)
    ip_address_map: dict[str, Any] = dataclass_field(default_factory=dict)
    primary_ipv4_id: str | None = None
    warnings: list[str] = dataclass_field(default_factory=list)
    cleaned_interfaces: set[str] = dataclass_field(default_factory=set)
    interfaces_deleted: int = 0
    interface_id_map: dict[str, str] = dataclass_field(default_factory=dict)

    def to_result(self) -> InterfaceUpdateResult:
        return InterfaceUpdateResult(
            interfaces_created=len(self.created_interfaces),
            interfaces_updated=len(self.updated_interfaces),
            interfaces_failed=len(self.failed_interfaces),
            interfaces_deleted=self.interfaces_deleted,
            ip_addresses_created=len(self.ip_address_map),
            primary_ip4_id=self.primary_ipv4_id,
            warnings=self.warnings,
        )
