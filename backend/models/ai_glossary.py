"""Request and response models for the assistant glossary (admin only).

Two kinds share one table: ``inventory_filter`` (a word -> a filter for the inventory assistant)
and ``workflow_step`` (a word -> one registry step id for the workflow assistant).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from services.ai_assistant.inventory_filter import FilterInput

MAX_TERM_CHARS = 64
MAX_ALIASES = 10
# ASCII letters, digits, space and a few separators; the settings form uses the same set. No commas
# (the form separates aliases with them), angle brackets or control characters: the term is echoed
# to the model in a tool result.
TERM_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9 ._/+&-]*$"
_TERM = re.compile(TERM_PATTERN)

KIND_INVENTORY = "inventory_filter"
KIND_STEP = "workflow_step"
GlossaryKind = Literal["inventory_filter", "workflow_step"]


def _clean_term(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned or not _TERM.match(cleaned):
        raise ValueError("use letters, digits, spaces and . _ / + & - only")
    return cleaned


class _TermBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    term: str = Field(min_length=1, max_length=MAX_TERM_CHARS)
    aliases: list[Annotated[str, Field(min_length=1, max_length=MAX_TERM_CHARS)]] = Field(
        default_factory=list, max_length=MAX_ALIASES
    )
    # For administrators only; never sent to the model.
    note: str | None = Field(default=None, max_length=300)

    @field_validator("term")
    @classmethod
    def _term_ok(cls, value: str) -> str:
        return _clean_term(value)

    @field_validator("aliases")
    @classmethod
    def _aliases_ok(cls, values: list[str]) -> list[str]:
        return [_clean_term(v) for v in values]


class InventoryTermBody(_TermBody):
    kind: Literal["inventory_filter"]
    filter: FilterInput
    # The Nautobot source whose names the filter values are checked against.
    source_id: str = Field(min_length=1, max_length=64)


class StepAliasBody(_TermBody):
    kind: Literal["workflow_step"]
    step_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")


GlossaryTermBody = Annotated[InventoryTermBody | StepAliasBody, Field(discriminator="kind")]
_BODY_ADAPTER: TypeAdapter[InventoryTermBody | StepAliasBody] = TypeAdapter(GlossaryTermBody)


def parse_term_body(data: dict[str, Any]) -> InventoryTermBody | StepAliasBody:
    """Validate a raw body the way the router does (used by callers outside FastAPI)."""
    return _BODY_ADAPTER.validate_python(data)


class GlossaryTermResponse(BaseModel):
    id: int
    kind: GlossaryKind
    term: str
    aliases: list[str]
    # inventory_filter: the FilterInput shape; workflow_step: {"step_id": ...}
    payload: dict[str, Any]
    note: str | None
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None


class GlossaryListResponse(BaseModel):
    items: list[GlossaryTermResponse]
    total: int
