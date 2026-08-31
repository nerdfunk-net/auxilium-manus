"""Pydantic models for Nautobot device source and saved inventories."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, Field, model_validator


class NautobotSourceRef(BaseModel):
    """Identifies a saved Nautobot source; the server looks up url/token."""

    source_id: str = Field(..., min_length=1, max_length=64)
    timeout: float = Field(default=30.0, ge=1, le=120)


class NautobotTestConnectionRequest(BaseModel):
    """Unsaved form values, or ``source_id`` to test stored credentials."""

    url: str | None = Field(default=None, min_length=1)
    credential_id: int | None = Field(default=None, gt=0)
    verify_ssl: bool = True
    timeout: float = Field(default=30.0, ge=1, le=120)
    source_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_source_or_credentials(self) -> Self:
        has_source = bool((self.source_id or "").strip())
        has_credentials = bool((self.url or "").strip()) and self.credential_id is not None
        if has_source == has_credentials:
            raise ValueError("Provide either source_id or both url and credential_id")
        return self


class NautobotTestConnectionResponse(BaseModel):
    success: bool
    message: str


class CreateInventoryRequest(BaseModel):
    name: str
    description: str | None = None
    conditions: list[dict[str, Any]] | None = None
    inventory_type: str = "filter"
    device_ids: list[str] | None = None
    template_category: str | None = None
    template_name: str | None = None
    scope: str = "global"
    group_path: str | None = None


class UpdateInventoryRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    conditions: list[dict[str, Any]] | None = None
    inventory_type: str | None = None
    device_ids: list[str] | None = None
    template_category: str | None = None
    template_name: str | None = None
    scope: str | None = None
    group_path: str | None = None


class InventoryResponse(BaseModel):
    id: int
    name: str
    description: str | None
    conditions: list[dict[str, Any]]
    inventory_type: str = "filter"
    device_ids: list[str] | None = None
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


class InventoryPreviewRequest(NautobotSourceRef):
    operations: list[LogicalOperation] = Field(default_factory=list)


class DeviceIdsPreviewRequest(NautobotSourceRef):
    """Preview an explicit, static list of Nautobot device IDs (no logical expression)."""

    device_ids: list[str] = Field(default_factory=list)


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


class FieldValuesRequest(NautobotSourceRef):
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


class DeviceSearchRequest(NautobotSourceRef):
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


class DeviceDetailsRequest(NautobotSourceRef):
    """Fetch full Nautobot device details by ID."""

    device_id: str = Field(..., min_length=1)


class DeviceAttributesRequest(NautobotSourceRef):
    """Fetch the Nautobot attribute bag for a device (template editor preview)."""

    device_id: str = Field(..., min_length=1)
    list_of_attributes: list[str] = Field(default_factory=list)
