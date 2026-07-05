"""Request/response models for update-attribute editor APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class RegexFlagsModel(BaseModel):
    case_insensitive: bool = False
    multiline: bool = False
    dotall: bool = False


class UpdateAttributeProbeRequest(BaseModel):
    sample_text: str
    pattern: str
    destination_template: str
    regex_flags: RegexFlagsModel = Field(default_factory=RegexFlagsModel)


class UpdateAttributeProbeDeviceRequest(BaseModel):
    device: dict[str, Any]
    source_path: str
    pattern: str
    destination_template: str
    regex_flags: RegexFlagsModel = Field(default_factory=RegexFlagsModel)


class UpdateAttributeProbeResponse(BaseModel):
    matched: bool
    source_text: str | None = None
    full_match: str | None = None
    groups: dict[str, str] = Field(default_factory=dict)
    named_groups: dict[str, str] = Field(default_factory=dict)
    destination_value: str | None = None
