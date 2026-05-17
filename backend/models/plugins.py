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
    description: str = Field(..., min_length=1)


class PluginMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mandatory_input: list[PluginIOField] = Field(default_factory=list)
    configuration_input: list[PluginIOField] = Field(default_factory=list)
    supported_output: list[PluginIOField] = Field(default_factory=list)
    outcomes: list[PluginOutcome] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_outcome_names(self) -> "PluginMetadata":
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


class DeviceSelectionPreviewRequest(BaseModel):
    inventory_source: str = Field(..., min_length=1)
    device_filter: dict[str, str] = Field(default_factory=dict)


class DevicePreview(BaseModel):
    name: str
    site: str | None = None
    role: str | None = None
    status: str | None = None


class DeviceSelectionPreviewResponse(BaseModel):
    devices: list[DevicePreview]
    total: int
