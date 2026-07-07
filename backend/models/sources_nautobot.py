"""Pydantic models for Nautobot device source and saved inventories."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class NautobotConnection(BaseModel):
    """Per-request Nautobot credentials (workflow step or API caller)."""

    nautobot_url: str = Field(..., min_length=1)
    nautobot_token: str = Field(..., min_length=1)
    timeout: float = Field(default=30.0, ge=1, le=120)


class CreateInventoryRequest(BaseModel):
    name: str
    description: str | None = None
    conditions: list[dict[str, Any]]
    template_category: str | None = None
    template_name: str | None = None
    scope: str = "global"
    group_path: str | None = None


class UpdateInventoryRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    conditions: list[dict[str, Any]] | None = None
    template_category: str | None = None
    template_name: str | None = None
    scope: str | None = None
    group_path: str | None = None


class InventoryResponse(BaseModel):
    id: int
    name: str
    description: str | None
    conditions: list[dict[str, Any]]
    template_category: str | None
    template_name: str | None
    scope: str
    group_path: str | None = None
    created_by: str
    is_active: bool
    created_at: str | None = None
    updated_at: str | None = None


class ListInventoriesResponse(BaseModel):
    inventories: list[InventoryResponse]
    total: int


class GroupsResponse(BaseModel):
    groups: list[str]


class InventoryDeleteResponse(BaseModel):
    success: bool
    message: str


class ImportInventoryRequest(BaseModel):
    import_data: dict[str, Any]


class LogicalCondition(BaseModel):
    field: str
    operator: str
    value: str


class LogicalOperation(BaseModel):
    operation_type: str
    conditions: list[LogicalCondition] = Field(default_factory=list)
    nested_operations: list[LogicalOperation] = Field(default_factory=list)


LogicalOperation.model_rebuild()


class InventoryPreviewRequest(NautobotConnection):
    operations: list[LogicalOperation] = Field(default_factory=list)


class DeviceInfo(BaseModel):
    id: str
    name: str | None = None
    serial: str | None = None
    location: str | None = None
    role: str | None = None
    tags: list[str] = Field(default_factory=list)
    device_type: str | None = None
    manufacturer: str | None = None
    platform: str | None = None
    platform_network_driver: str | None = None
    primary_ip4: str | None = None
    status: str | None = None


class InventoryPreviewResponse(BaseModel):
    devices: list[DeviceInfo]
    total_count: int
    operations_executed: int


class FieldValuesRequest(NautobotConnection):
    field: str = Field(..., min_length=1)


class FieldValuesResponse(BaseModel):
    field: str
    values: list[dict[str, str]] | list[str] = Field(default_factory=list)
    input_type: str = "text"


class RenameGroupRequest(BaseModel):
    old_path: str
    new_name: str


class RenameGroupResponse(BaseModel):
    updated_count: int
    new_path: str


class NautobotCredentialsQuery(BaseModel):
    """Query parameters for Nautobot-backed GET endpoints."""

    nautobot_url: str = Field(..., min_length=1)
    nautobot_token: str = Field(..., min_length=1)


class DeviceSearchRequest(NautobotConnection):
    """Search Nautobot devices by (partial) name."""

    search: str = Field(..., min_length=1)
    limit: int = Field(default=20, ge=1, le=100)


class DeviceSummary(BaseModel):
    id: str
    name: str | None = None
    primary_ip4: str | None = None
    platform: str | None = None
    network_driver: str | None = None


class DeviceSearchResponse(BaseModel):
    devices: list[DeviceSummary]


class DeviceDetailsRequest(NautobotConnection):
    """Fetch full Nautobot device details by ID."""

    device_id: str = Field(..., min_length=1)
