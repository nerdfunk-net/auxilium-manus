"""Pydantic models for Batfish source configuration and ad-hoc queries."""

from __future__ import annotations

from typing import Any, Literal, Self

from pydantic import BaseModel, Field, model_validator

from services.settings.source_keys import SOURCE_ID_PATTERN

_SOURCE_ID_REGEX = SOURCE_ID_PATTERN.pattern


class BatfishSourceCreateRequest(BaseModel):
    source_id: str = Field(..., pattern=_SOURCE_ID_REGEX, max_length=64)
    host: str = Field(..., min_length=1, max_length=255)
    port: int = Field(default=9996, ge=1, le=65535)


class BatfishSourceUpdateRequest(BaseModel):
    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)


class BatfishTestConnectionRequest(BaseModel):
    """Unsaved form values, or ``source_id`` to test a stored source."""

    host: str | None = Field(default=None, min_length=1, max_length=255)
    port: int = Field(default=9996, ge=1, le=65535)
    source_id: str | None = Field(default=None, min_length=1, max_length=64)

    @model_validator(mode="after")
    def validate_source_or_inline(self) -> Self:
        has_source = bool((self.source_id or "").strip())
        has_inline = bool((self.host or "").strip())
        if has_source == has_inline:
            raise ValueError("Provide either source_id or host")
        return self


class BatfishSourceResponse(BaseModel):
    source_id: str
    host: str
    port: int


class BatfishSourceListResponse(BaseModel):
    sources: list[BatfishSourceResponse]
    total: int


class BatfishTestConnectionResponse(BaseModel):
    success: bool
    message: str


BatfishQueryQuestion = Literal["routes", "reachability", "testFilters"]


class BatfishRoutesQueryRequest(BaseModel):
    """Ad-hoc counterpart of the batfish-routing-table step's config fields."""

    network: str = Field(..., min_length=1)
    snapshot: str | None = Field(default=None)
    nodes: str | None = None
    network_prefix: str | None = None
    prefix_match_type: str | None = None
    protocols: str | None = None
    vrfs: str | None = None
    rib: str | None = None


class BatfishReachabilityQueryRequest(BaseModel):
    """Ad-hoc counterpart of the batfish-path-check step's config fields."""

    network: str = Field(..., min_length=1)
    snapshot: str | None = None
    start_node: str = Field(..., min_length=1)
    end_node: str | None = None
    dst_ips: str | None = None
    src_ips: str | None = None
    applications: list[str] | None = None
    ip_protocols: str | None = None
    max_traces: int | None = Field(default=None, ge=1)
    invert_search: bool = False
    ignore_filters: bool = False


class BatfishTestFiltersQueryRequest(BaseModel):
    """Ad-hoc counterpart of the batfish-acl-check step's config fields."""

    network: str = Field(..., min_length=1)
    snapshot: str | None = None
    node: str = Field(..., min_length=1)
    filter_name: str = Field(..., min_length=1)
    dst_ips: str = Field(..., min_length=1)
    src_ips: str | None = None
    applications: list[str] | None = None
    ip_protocols: str | None = None
    start_location: str | None = None


class BatfishQueryResponse(BaseModel):
    success: bool
    question: BatfishQueryQuestion
    network: str
    snapshot: str
    rows: list[dict[str, Any]]
    reachable: bool | None = None
    action: str | None = None
    error: str | None = None
