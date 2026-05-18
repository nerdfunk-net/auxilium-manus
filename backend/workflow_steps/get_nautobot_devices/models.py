"""Pydantic models for device-selection inventory queries."""
from __future__ import annotations

from pydantic import BaseModel, Field


class LogicalCondition(BaseModel):
    field: str
    operator: str
    value: str


class LogicalOperation(BaseModel):
    operation_type: str = Field(..., description="AND, OR, or NOT")
    conditions: list[LogicalCondition] = Field(default_factory=list)
    nested_operations: list[LogicalOperation] = Field(default_factory=list)


LogicalOperation.model_rebuild()


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
    primary_ip4: str | None = None
    status: str | None = None
