"""
Type models for device update operations.

These Pydantic models provide type safety and validation for device update workflows.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator


class DeviceIdentifier(BaseModel):
    """
    Device identification parameters.

    At least one of the fields must be provided to identify a device.
    """

    id: Optional[str] = Field(None, description="Device UUID")
    name: Optional[str] = Field(None, description="Device name")
    ip_address: Optional[str] = Field(None, description="Primary IPv4 address")

    @field_validator("id", "name", "ip_address")
    @classmethod
    def validate_not_empty(cls, v: Optional[str]) -> Optional[str]:
        """Ensure string values are not empty."""
        if v is not None and isinstance(v, str) and not v.strip():
            return None
        return v

    def model_post_init(self, __context: Any) -> None:
        """Validate that at least one identifier is provided."""
        if not any([self.id, self.name, self.ip_address]):
            raise ValueError(
                "At least one identifier must be provided: id, name, or ip_address"
            )


class InterfaceConfig(BaseModel):
    """
    Interface configuration for device updates (legacy primary_ip4 updates).

    Used when updating a device's primary_ip4 field to configure how the
    management interface should be created or updated.
    """

    name: str = Field(default="Loopback", description="Interface name")
    type: str = Field(default="virtual", description="Interface type")
    status: str = Field(default="active", description="Interface status")
    mgmt_interface_create_on_ip_change: bool = Field(
        default=False,
        description="Create new interface when IP changes (vs updating existing)",
    )
    add_prefixes_automatically: bool = Field(
        default=False,
        description="Automatically create parent prefix if it doesn't exist",
    )
    use_assigned_ip_if_exists: bool = Field(
        default=False,
        description="Use existing IP if already assigned to another device",
    )


class InterfaceSpec(BaseModel):
    """
    Specification for interface creation or update.

    Used when creating/updating multiple interfaces through the interfaces parameter.
    """

    name: str = Field(..., description="Interface name")
    type: str = Field(..., description="Interface type (e.g., '1000base-t', 'virtual')")
    status: str = Field(default="active", description="Interface status")
    ip_address: Optional[str] = Field(
        None, description="IP address with prefix (e.g., '192.168.1.1/24')"
    )
    namespace: Optional[str] = Field(
        default="Global", description="IP namespace (required if ip_address provided)"
    )
    is_primary_ipv4: bool = Field(
        default=False, description="Set this IP as primary IPv4 for the device"
    )
    enabled: Optional[bool] = Field(None, description="Interface enabled state")
    mgmt_only: Optional[bool] = Field(
        None, description="Mark interface as management only"
    )
    description: Optional[str] = Field(None, description="Interface description")
    mac_address: Optional[str] = Field(None, description="MAC address")
    mtu: Optional[int] = Field(None, description="MTU size")
    mode: Optional[str] = Field(None, description="Interface mode")
    ip_role: Optional[str] = Field(
        None, description="IP address role (e.g., 'Secondary', 'Anycast')"
    )

    @field_validator("namespace")
    @classmethod
    def validate_namespace_with_ip(cls, v: Optional[str], info) -> Optional[str]:
        """Ensure namespace is provided when ip_address is specified."""
        if info.data.get("ip_address") and not v:
            raise ValueError("namespace is required when ip_address is provided")
        return v


class DeviceUpdateResult(BaseModel):
    """Result of a device update operation."""

    success: bool = Field(..., description="Whether the update succeeded")
    device_id: Optional[str] = Field(None, description="Device UUID")
    device_name: str = Field(..., description="Device name")
    message: str = Field(..., description="Human-readable status message")
    updated_fields: list[str] = Field(
        default_factory=list, description="List of fields that were updated"
    )
    warnings: list[str] = Field(
        default_factory=list, description="List of warning messages"
    )
    interfaces_created: int = Field(
        default=0, description="Number of interfaces created"
    )
    interfaces_updated: int = Field(
        default=0, description="Number of interfaces updated"
    )
    interfaces_failed: int = Field(
        default=0, description="Number of interface operations that failed"
    )
    details: Dict[str, Any] = Field(
        default_factory=dict,
        description="Detailed information about the update (before/after/changes)",
    )


class InterfaceUpdateResult(BaseModel):
    """Result of interface update operations."""

    interfaces_created: int = Field(
        default=0, description="Number of interfaces created"
    )
    interfaces_updated: int = Field(
        default=0, description="Number of interfaces updated"
    )
    interfaces_failed: int = Field(
        default=0, description="Number of interface operations that failed"
    )
    interfaces_deleted: int = Field(
        default=0, description="Number of interfaces deleted during sync"
    )
    ip_addresses_created: int = Field(
        default=0, description="Number of IP addresses created"
    )
    primary_ip4_id: Optional[str] = Field(None, description="Primary IPv4 ID if set")
    warnings: list[str] = Field(
        default_factory=list, description="List of warning messages"
    )
