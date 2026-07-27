"""
Type models for device update operations.

These Pydantic models provide type safety and validation for device update workflows.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator


class DeviceIdentifier(BaseModel):
    """
    Device identification parameters.

    At least one of the fields must be provided to identify a device.
    """

    id: str | None = Field(None, description="Device UUID")
    name: str | None = Field(None, description="Device name")
    ip_address: str | None = Field(None, description="Primary IPv4 address")

    @field_validator("id", "name", "ip_address")
    @classmethod
    def validate_not_empty(cls, v: str | None) -> str | None:
        """Ensure string values are not empty."""
        if v is not None and isinstance(v, str) and not v.strip():
            return None
        return v

    def model_post_init(self, __context: Any) -> None:
        """Validate that at least one identifier is provided."""
        if not any([self.id, self.name, self.ip_address]):
            raise ValueError("At least one identifier must be provided: id, name, or ip_address")


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
    ip_address: str | None = Field(
        None, description="IP address with prefix (e.g., '192.168.1.1/24')"
    )
    namespace: str | None = Field(
        default="Global", description="IP namespace (required if ip_address provided)"
    )
    is_primary_ipv4: bool = Field(
        default=False, description="Set this IP as primary IPv4 for the device"
    )
    enabled: bool | None = Field(None, description="Interface enabled state")
    mgmt_only: bool | None = Field(None, description="Mark interface as management only")
    description: str | None = Field(None, description="Interface description")
    mac_address: str | None = Field(None, description="MAC address")
    mtu: int | None = Field(None, description="MTU size")
    mode: str | None = Field(None, description="Interface mode")
    ip_role: str | None = Field(None, description="IP address role (e.g., 'Secondary', 'Anycast')")

    @field_validator("namespace")
    @classmethod
    def validate_namespace_with_ip(cls, v: str | None, info) -> str | None:
        """Ensure namespace is provided when ip_address is specified."""
        if info.data.get("ip_address") and not v:
            raise ValueError("namespace is required when ip_address is provided")
        return v


class DeviceUpdateResult(BaseModel):
    """Result of a device update operation."""

    success: bool = Field(..., description="Whether the update succeeded")
    device_id: str | None = Field(None, description="Device UUID")
    device_name: str = Field(..., description="Device name")
    message: str = Field(..., description="Human-readable status message")
    updated_fields: list[str] = Field(
        default_factory=list, description="List of fields that were updated"
    )
    warnings: list[str] = Field(default_factory=list, description="List of warning messages")
    interfaces_created: int = Field(default=0, description="Number of interfaces created")
    interfaces_updated: int = Field(default=0, description="Number of interfaces updated")
    interfaces_failed: int = Field(
        default=0, description="Number of interface operations that failed"
    )
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Detailed information about the update (before/after/changes)",
    )


class InterfaceUpdateResult(BaseModel):
    """Result of interface update operations."""

    interfaces_created: int = Field(default=0, description="Number of interfaces created")
    interfaces_updated: int = Field(default=0, description="Number of interfaces updated")
    interfaces_failed: int = Field(
        default=0, description="Number of interface operations that failed"
    )
    interfaces_deleted: int = Field(
        default=0, description="Number of interfaces deleted during sync"
    )
    ip_addresses_created: int = Field(default=0, description="Number of IP addresses created")
    primary_ip4_id: str | None = Field(None, description="Primary IPv4 ID if set")
    warnings: list[str] = Field(default_factory=list, description="List of warning messages")


class AddDeviceRequest(BaseModel):
    """Request to create a new device in Nautobot.

    ``name``/``role``/``status``/``location``/``device_type`` accept either a
    Nautobot name or an already-resolved UUID — ``DeviceCreationService`` resolves
    names to UUIDs before creating the device. All other fields are optional.
    """

    name: str = Field(..., description="Device name")
    role: str = Field(..., description="Role name or UUID")
    status: str = Field(..., description="Status name or UUID")
    location: str = Field(..., description="Location name or UUID")
    device_type: str = Field(..., description="Device type model or UUID")

    platform: str | None = Field(None, description="Platform name or UUID")
    software_version: str | None = Field(None, description="Software version")
    serial: str | None = Field(None, description="Serial number")
    asset_tag: str | None = Field(None, description="Asset tag")
    tags: list[str] | None = Field(None, description="Tag names or UUIDs")
    custom_fields: dict[str, str] | None = Field(None, description="Custom field values")

    rack: str | None = Field(None, description="Rack name or UUID")
    face: str | None = Field(None, description="Rack face: front or rear")
    position: int | None = Field(None, description="Rack U position")

    interfaces: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Interfaces to create, same shape as DeviceUpdateService interfaces",
    )
    add_prefix: bool = Field(default=True, description="Auto-create missing IP prefixes")
    default_prefix_length: str = Field(
        default="/24", description="Default prefix length for bare IP addresses"
    )

    virtual_chassis_id: str | None = Field(
        None, description="Existing virtual chassis UUID to join"
    )
    new_virtual_chassis_name: str | None = Field(
        None,
        description="Create a new virtual chassis with this name; device becomes master",
    )

    dry_run: bool = Field(default=False, description="Validate without creating the device")
