"""Request/response models for Jinja template editor APIs."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class JinjaValidateRequest(BaseModel):
    template: str


class JinjaValidateResponse(BaseModel):
    valid: bool = True


class JinjaPreviewRequest(BaseModel):
    template: str
    context: dict[str, Any] = Field(default_factory=dict)


class JinjaPreviewResponse(BaseModel):
    rendered: str


class JinjaSampleContextFromNautobotRequest(BaseModel):
    nautobot_source_id: str
    device_name: str
    list_of_attributes: list[str] = Field(default_factory=list)


class JinjaSampleContextFromDeviceRequest(BaseModel):
    device: dict[str, Any]


class JinjaSampleContextResponse(BaseModel):
    context: dict[str, Any]
