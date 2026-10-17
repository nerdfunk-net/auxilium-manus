"""Request/response models for update-content editor APIs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class RegexFlagsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_insensitive: bool = False
    multiline: bool = False
    dotall: bool = False


class UpdateContentProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sample_text: str = Field(max_length=1_000_000)
    pattern: str = Field(max_length=1_000)
    replacement: str = Field(max_length=10_000)
    regex_flags: RegexFlagsModel = Field(default_factory=RegexFlagsModel)
    replace_all: bool = True


class UpdateContentProbeResponse(BaseModel):
    matched: bool
    match_count: int
    updated_text: str | None = None
