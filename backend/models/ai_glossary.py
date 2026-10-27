"""Request and response models for the inventory assistant glossary (admin only)."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.ai_assistant.inventory_filter import FilterInput

MAX_TERM_CHARS = 64
MAX_ALIASES = 10
# ASCII letters, digits, space and a few separators; the settings form uses the same set. No commas
# (the form separates aliases with them), angle brackets or control characters: the term is echoed
# to the model in a tool result.
TERM_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 ._/+&-]*$"
_TERM = re.compile(TERM_PATTERN)


def _clean_term(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned or not _TERM.match(cleaned):
        raise ValueError("use letters, digits, spaces and . _ / + & - only")
    return cleaned


class GlossaryTermBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: str = Field(min_length=1, max_length=MAX_TERM_CHARS)
    aliases: list[Annotated[str, Field(min_length=1, max_length=MAX_TERM_CHARS)]] = Field(
        default_factory=list, max_length=MAX_ALIASES
    )
    filter: FilterInput
    # For administrators only; never sent to the model.
    note: str | None = Field(default=None, max_length=300)
    # The Nautobot source whose names the filter values are checked against.
    source_id: str = Field(min_length=1, max_length=64)

    @field_validator("term")
    @classmethod
    def _term_ok(cls, value: str) -> str:
        return _clean_term(value)

    @field_validator("aliases")
    @classmethod
    def _aliases_ok(cls, values: list[str]) -> list[str]:
        return [_clean_term(v) for v in values]


class GlossaryTermCreate(GlossaryTermBase):
    pass


class GlossaryTermUpdate(GlossaryTermBase):
    """Full replacement of one entry."""


class GlossaryTermResponse(BaseModel):
    id: int
    term: str
    aliases: list[str]
    filter: dict[str, Any]
    note: str | None
    # Set by create / update: values Nautobot could not confirm.
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GlossaryListResponse(BaseModel):
    items: list[GlossaryTermResponse]
    total: int
