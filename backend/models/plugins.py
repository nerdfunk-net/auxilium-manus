from __future__ import annotations

from pathlib import PurePath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PluginIOField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    data_type: str = Field(..., min_length=1)
    required: bool = False
    default: Any = None
    example: Any = None


class PluginOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, pattern=r"^[a-z][a-z0-9_-]*$")
    description: str = Field(default="", min_length=0)
    data_type: str | None = None
    example: Any = None


class PluginStepOutcome(BaseModel):
    """Named exit path for capability-based workflow routing."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, pattern=r"^[a-z][a-z0-9_-]*$")


class PluginMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mandatory_input: list[PluginIOField] = Field(default_factory=list)
    configuration_input: list[PluginIOField] = Field(default_factory=list)
    outcomes: list[PluginOutcome] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_outcome_names(self) -> PluginMetadata:
        outcome_names = [outcome.name for outcome in self.outcomes]

        if len(outcome_names) != len(set(outcome_names)):
            raise ValueError("outcome names must be unique within a plugin")

        return self


class PluginDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    artifact_type: str = Field(..., min_length=1)
    directory: str = Field(..., min_length=1)
    enabled: bool = True
    requires: list[str] = Field(default_factory=list)
    produces: list[str] = Field(default_factory=list)
    consumes: list[str] = Field(default_factory=list)
    requires_parsed: list[str] = Field(default_factory=list)
    produces_parsed: list[str] = Field(default_factory=list)
    outcomes: list[PluginStepOutcome] = Field(default_factory=list)
    metadata: PluginMetadata

    @field_validator("directory")
    @classmethod
    def validate_directory(cls, directory: str) -> str:
        path = PurePath(directory)

        if path.is_absolute() or ".." in path.parts:
            raise ValueError("directory must be a relative path without parent traversal")

        return directory


class PluginRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(..., ge=1)
    plugins: list[PluginDefinition] = Field(default_factory=list)


class PluginListResponse(BaseModel):
    plugins: list[PluginDefinition]


class PluginRegistryResponse(BaseModel):
    schema_version: int
    plugins: list[PluginDefinition]


class LogicalConditionRequest(BaseModel):
    field: str
    operator: str
    value: str


class LogicalOperationRequest(BaseModel):
    operation_type: str
    conditions: list[LogicalConditionRequest] = Field(default_factory=list)
    nested_operations: list[LogicalOperationRequest] = Field(default_factory=list)


LogicalOperationRequest.model_rebuild()


class DeviceSelectionPreviewRequest(BaseModel):
    nautobot_url: str = Field(..., min_length=1)
    nautobot_token: str = Field(..., min_length=1)
    operations: list[LogicalOperationRequest] = Field(default_factory=list)


class DevicePreview(BaseModel):
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


class DeviceSelectionPreviewResponse(BaseModel):
    devices: list[DevicePreview]
    total: int


class FieldOption(BaseModel):
    value: str
    label: str


class FieldOptionsResponse(BaseModel):
    fields: list[FieldOption]
    operators: list[FieldOption]


class FieldValuesRequest(BaseModel):
    nautobot_url: str = Field(..., min_length=1)
    nautobot_token: str = Field(..., min_length=1)
    field: str = Field(..., min_length=1)


class FieldValuesResponse(BaseModel):
    field: str
    values: list[str]
    input_type: str
