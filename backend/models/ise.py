"""Pydantic models for Cisco ISE source configuration and NetworkDevice CRUD."""

from __future__ import annotations

from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from services.settings.source_keys import SOURCE_ID_PATTERN

_SOURCE_ID_REGEX = SOURCE_ID_PATTERN.pattern


class ISESourceCreateRequest(BaseModel):
    source_id: str = Field(..., pattern=_SOURCE_ID_REGEX, max_length=64)
    url: str = Field(..., min_length=1)
    credential_id: int = Field(..., gt=0)
    verify_ssl: bool = True
    timeout: float = Field(default=30.0, ge=1, le=120)


class ISESourceUpdateRequest(BaseModel):
    url: str | None = Field(default=None, min_length=1)
    credential_id: int | None = Field(default=None, gt=0)
    verify_ssl: bool | None = None
    timeout: float | None = Field(default=None, ge=1, le=120)


class ISETestConnectionRequest(BaseModel):
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


class ISESourceResponse(BaseModel):
    source_id: str
    url: str
    verify_ssl: bool
    timeout: float
    credential_id: int | None = None
    credential_name: str | None = None


class ISESourceListResponse(BaseModel):
    sources: list[ISESourceResponse]
    total: int


class ISETestConnectionResponse(BaseModel):
    success: bool
    message: str


class ISEDeviceIP(BaseModel):
    ipaddress: str
    mask: int = Field(..., ge=0, le=32)


class ISENetworkDeviceCreate(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str = Field(..., min_length=1)
    description: str | None = None
    profileName: str = "Cisco"
    coaPort: int | None = None
    NetworkDeviceIPList: list[ISEDeviceIP] = Field(default_factory=list)
    NetworkDeviceGroupList: list[str] | None = None
    authenticationSettings: dict[str, Any] | None = None
    snmpsettings: dict[str, Any] | None = None
    tacacsSettings: dict[str, Any] | None = None


class ISENetworkDeviceUpdate(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str | None = None
    description: str | None = None
    profileName: str | None = None
    coaPort: int | None = None
    NetworkDeviceIPList: list[ISEDeviceIP] | None = None
    NetworkDeviceGroupList: list[str] | None = None
    authenticationSettings: dict[str, Any] | None = None
    snmpsettings: dict[str, Any] | None = None
    tacacsSettings: dict[str, Any] | None = None


class ISENetworkDeviceResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str | None = None
    name: str | None = None
    description: str | None = None


class ISENetworkDeviceListResponse(BaseModel):
    total: int
    resources: list[dict[str, Any]]
    next_page: str | None = None


class ISELocationCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    parent_group: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description=(
            "Name of the existing parent location, e.g. 'All Locations' or, for "
            "a nested location, 'All Locations#Building1'."
        ),
    )

    @field_validator("name")
    @classmethod
    def _no_hash(cls, value: str) -> str:
        if "#" in value:
            raise ValueError("must not contain '#' (reserved for ISE group hierarchy)")
        return value.strip()

    @field_validator("parent_group")
    @classmethod
    def _strip_parent_group(cls, value: str) -> str:
        return value.strip()


class ISELocationResponse(BaseModel):
    id: str | None = None
    name: str
    description: str | None = None
    parent_group: str


class ISEDeviceGroupRootCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)

    @field_validator("name")
    @classmethod
    def _no_hash(cls, value: str) -> str:
        if "#" in value:
            raise ValueError("must not contain '#' (reserved for ISE group hierarchy)")
        return value.strip()


class ISEDeviceGroupChildCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=1000)
    parent_group: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description=(
            "Full existing group name, e.g. 'Location#All Locations' or 'nautobot#nautobot'."
        ),
    )

    @field_validator("name")
    @classmethod
    def _no_hash(cls, value: str) -> str:
        if "#" in value:
            raise ValueError("must not contain '#' (reserved for ISE group hierarchy)")
        return value.strip()

    @field_validator("parent_group")
    @classmethod
    def _strip_parent_group(cls, value: str) -> str:
        return value.strip()


class ISEDeviceGroupUpdateRequest(BaseModel):
    description: str = Field(..., max_length=1000)


class ISEDeviceGroupResponse(BaseModel):
    id: str | None = None
    name: str
    description: str | None = None
    othername: str | None = None


class ISEDeviceGroupListResponse(BaseModel):
    total: int
    resources: list[dict[str, Any]]
    next_page: str | None = None
