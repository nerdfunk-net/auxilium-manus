"""Pydantic request/response models for Netmiko Jinja2 templates."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TemplateVariable(BaseModel):
    """A user-defined template variable and its stored value."""

    value: str = ""
    type: str = "custom"


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    template_type: str = Field(default="jinja2", max_length=50)
    category: str = Field(default="netmiko", max_length=100)
    content: str = ""
    variables: dict[str, TemplateVariable] = Field(default_factory=dict)
    pre_run_commands: list[str] = Field(default_factory=list)
    pre_run_use_textfsm: bool = False
    nautobot_attributes: list[str] = Field(default_factory=list)
    credential_id: int | None = None


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    template_type: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, max_length=100)
    content: str | None = None
    variables: dict[str, TemplateVariable] | None = None
    pre_run_commands: list[str] | None = None
    pre_run_use_textfsm: bool | None = None
    nautobot_attributes: list[str] | None = None
    credential_id: int | None = None


class TemplateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    source: str
    template_type: str
    category: str
    description: str | None
    content: str
    variables: dict[str, Any]
    pre_run_commands: list[str] = Field(default_factory=list)
    pre_run_use_textfsm: bool = False
    nautobot_attributes: list[str] = Field(default_factory=list)
    credential_id: int | None
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


class TemplateRenderRequest(BaseModel):
    template_content: str = Field(..., description="Jinja2 template content to render")
    variables: dict[str, Any] = Field(
        default_factory=dict,
        description="Rendering context variables (nested objects allowed)",
    )


class TemplateRenderResponse(BaseModel):
    rendered_content: str
    variables_used: list[str]
    warnings: list[str] = Field(default_factory=list)
