"""Request/response models for update-content editor APIs."""

from __future__ import annotations

from pydantic import BaseModel, Field


class RegexFlagsModel(BaseModel):
    case_insensitive: bool = False
    multiline: bool = False
    dotall: bool = False


class UpdateContentProbeRequest(BaseModel):
    sample_text: str
    pattern: str
    replacement: str
    regex_flags: RegexFlagsModel = Field(default_factory=RegexFlagsModel)
    replace_all: bool = True


class UpdateContentProbeResponse(BaseModel):
    matched: bool
    match_count: int
    updated_text: str | None = None
