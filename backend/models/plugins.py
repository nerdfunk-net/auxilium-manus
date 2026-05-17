from __future__ import annotations

from pathlib import PurePath
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PluginIOField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    data_type: str = Field(..., min_length=1)
    required: bool = False
    example: Any = None


class PluginMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mandatory_input: list[PluginIOField] = Field(default_factory=list)
    configuration_input: list[PluginIOField] = Field(default_factory=list)
    supported_output: list[PluginIOField] = Field(default_factory=list)


class PluginDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(..., min_length=1)
    description: str = Field(..., min_length=1)
    artifact_type: str = Field(..., min_length=1)
    filename: str = Field(..., min_length=1)
    enabled: bool = True
    metadata: PluginMetadata

    @field_validator("filename")
    @classmethod
    def validate_filename(cls, filename: str) -> str:
        path = PurePath(filename)

        if path.is_absolute() or ".." in path.parts:
            raise ValueError("filename must be a relative path without parent traversal")

        return filename


class PluginRegistry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(..., ge=1)
    plugins: list[PluginDefinition] = Field(default_factory=list)


class PluginListResponse(BaseModel):
    plugins: list[PluginDefinition]


class PluginRegistryResponse(BaseModel):
    schema_version: int
    plugins: list[PluginDefinition]
