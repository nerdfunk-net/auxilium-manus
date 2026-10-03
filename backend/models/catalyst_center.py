"""Pydantic models for Cisco Catalyst Center: source config API + normalized domain objects.

The normalized models (``CatalystCenterDevice``, ``CatalystCenterCommandResult``) are the only
shapes workflow steps see; raw Intent API payloads stay inside ``services.catalyst_center``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.settings.source_keys import SOURCE_ID_PATTERN

_SOURCE_ID_REGEX = SOURCE_ID_PATTERN.pattern


class CatalystCenterSourceCreateRequest(BaseModel):
    source_id: str = Field(..., pattern=_SOURCE_ID_REGEX, max_length=64)
    url: str = Field(..., min_length=1)
    credential_id: int = Field(..., gt=0)
    verify_ssl: bool = True
    timeout: float = Field(default=30.0, ge=1, le=120)


class CatalystCenterSourceUpdateRequest(BaseModel):
    url: str | None = Field(default=None, min_length=1)
    credential_id: int | None = Field(default=None, gt=0)
    verify_ssl: bool | None = None
    timeout: float | None = Field(default=None, ge=1, le=120)


class CatalystCenterTestConnectionRequest(BaseModel):
    """Unsaved form values, or ``source_id`` to test stored credentials."""

    url: str | None = Field(default=None, min_length=1)
    credential_id: int | None = Field(default=None, gt=0)
    verify_ssl: bool = True
    timeout: float = Field(default=30.0, ge=1, le=120)
    source_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_source_or_inline(self) -> Self:
        has_source = bool((self.source_id or "").strip())
        has_inline = bool((self.url or "").strip()) and self.credential_id is not None
        if has_source == has_inline:
            raise ValueError("Provide either source_id or both url and credential_id")
        return self


class CatalystCenterSourceResponse(BaseModel):
    source_id: str
    url: str
    verify_ssl: bool
    timeout: float
    credential_id: int | None = None
    credential_name: str | None = None


class CatalystCenterSourceListResponse(BaseModel):
    sources: list[CatalystCenterSourceResponse]
    total: int


class CatalystCenterTestConnectionResponse(BaseModel):
    success: bool
    message: str
    release: str | None = None


class CatalystCenterDevicePreviewRequest(BaseModel):
    """Filters are validated by ``CatalystCenterDeviceFilters.from_config`` in the router."""

    filters: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=25, ge=1, le=100)


class CatalystCenterDevicePreviewItem(BaseModel):
    """Inventory summary shown in the step's preview; deliberately omits the raw record."""

    id: str
    hostname: str | None = None
    management_ip: str | None = None
    family: str | None = None
    role: str | None = None
    software_type: str | None = None
    software_version: str | None = None
    platform_id: str | None = None
    reachability_status: str | None = None


class CatalystCenterDevicePreviewResponse(BaseModel):
    devices: list[CatalystCenterDevicePreviewItem]
    truncated: bool


class CatalystCenterDevice(BaseModel):
    """One network device, normalized from ``GET /network-device`` (version independent)."""

    model_config = ConfigDict(frozen=True)

    id: str
    hostname: str | None = None
    management_ip: str | None = None
    mac_address: str | None = None
    platform_id: str | None = None
    family: str | None = None
    device_type: str | None = None
    serial_number: str | None = None
    software_version: str | None = None
    software_type: str | None = None
    role: str | None = None
    reachability_status: str | None = None
    collection_status: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class CatalystCenterSite(BaseModel):
    """One site/area/building/floor from ``GET /site`` (version independent)."""

    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    name_hierarchy: str


class CatalystCenterSiteListResponse(BaseModel):
    sites: list[CatalystCenterSite]
    total: int


class CatalystCenterCommandStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    BLOCKLISTED = "blocklisted"


class CatalystCenterCommandResult(BaseModel):
    """Output of one command-runner command on one device."""

    model_config = ConfigDict(frozen=True)

    device_id: str
    command: str
    status: CatalystCenterCommandStatus
    output: str
