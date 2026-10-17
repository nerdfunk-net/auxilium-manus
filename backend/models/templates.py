"""Pydantic request/response models for Netmiko Jinja2 templates."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ParseStructuredRequest(BaseModel):
    """Raw text to parse as YAML or JSON for the template editor's
    "Load variables from file" flow."""

    model_config = ConfigDict(extra="forbid")

    content: str = Field(
        ..., max_length=1_000_000, description="Raw file/paste content to parse"
    )
    format: Literal["yaml", "json", "auto"] = "auto"


class ParseStructuredResponse(BaseModel):
    parsed: Any


class TemplateVariable(BaseModel):
    """A user-defined template variable and its stored value."""

    value: str = ""
    type: str = "custom"


class BatfishQueryConfig(BaseModel):
    """Persisted Batfish query definition for the template editor's preview
    `batfish` variable. Only the query definition is persisted -- never the
    fetched answer itself, mirroring how parsed_config/command results also
    aren't saved with the template.
    """

    enabled: bool = False
    source_id: str | None = None
    network: str | None = None
    snapshot: str | None = None
    # "generic" is the Options modal's "Custom Question..." sentinel -- the
    # actual question name for that case is generic_question_name below, not
    # this field (mirrors frontend/.../templates/types.ts::BatfishEditorQuestion,
    # which is not the closed BatfishQueryQuestion Literal for the same reason).
    question: Literal["routes", "reachability", "testFilters", "generic"] | None = None
    generic_question_name: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    notes: str | None = Field(default=None, max_length=100_000)
    template_type: str = Field(default="jinja2", max_length=50)
    category: str = Field(default="netmiko", max_length=100)
    content: str = ""
    variables: dict[str, TemplateVariable] = Field(default_factory=dict)
    pre_run_commands: list[str] = Field(default_factory=list)
    pre_run_use_textfsm: bool = False
    nautobot_attributes: list[str] = Field(default_factory=list)
    credential_id: int | None = None
    batfish_config: BatfishQueryConfig | None = None


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    notes: str | None = Field(default=None, max_length=100_000)
    template_type: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=100)
    content: str | None = None
    variables: dict[str, TemplateVariable] | None = None
    pre_run_commands: list[str] | None = None
    pre_run_use_textfsm: bool | None = None
    nautobot_attributes: list[str] | None = None
    credential_id: int | None = None
    batfish_config: BatfishQueryConfig | None = None


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source: str
    template_type: str
    category: str
    description: str | None
    notes: str | None
    content: str
    variables: dict[str, Any]
    pre_run_commands: list[str] = Field(default_factory=list)
    pre_run_use_textfsm: bool = False
    nautobot_attributes: list[str] = Field(default_factory=list)
    credential_id: int | None
    batfish_config: BatfishQueryConfig | None = None
    created_by: str | None
    is_active: bool
    created_at: str | None
    updated_at: str | None


class TemplateListItem(BaseModel):
    """Template metadata without the (potentially large) content body."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source: str
    template_type: str
    category: str
    description: str | None
    created_by: str | None
    updated_at: str | None


class TemplateListResponse(BaseModel):
    templates: list[TemplateListItem]
    total: int


MAX_RENDER_TEMPLATE_CHARS = 200_000
MAX_RENDER_VARIABLES_CHARS = 1_000_000


class TemplateRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_content: str = Field(
        ..., max_length=MAX_RENDER_TEMPLATE_CHARS, description="Jinja2 template content to render"
    )
    variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Rendering context variables (nested objects allowed)",
    )

    @field_validator("variables")
    @classmethod
    def _bounded_variables(cls, value: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(value, default=str)) > MAX_RENDER_VARIABLES_CHARS:
            raise ValueError("variables are too large")
        return value


class TemplateRenderResponse(BaseModel):
    rendered_content: str
    variables_used: list[str]
    warnings: list[str] = Field(default_factory=list)
