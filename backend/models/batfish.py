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


class BatfishExtractFactsQueryRequest(BaseModel):
    """Ad-hoc counterpart of the batfish-extract-facts step's config fields."""

    network: str = Field(..., min_length=1)
    snapshot: str | None = None
    nodes_filter: str | None = None


class BatfishOspfFactsQueryRequest(BaseModel):
    """Ad-hoc counterpart of the batfish-ospf-facts step's config fields."""

    network: str = Field(..., min_length=1)
    snapshot: str | None = None
    nodes: str | None = None
    include_process: bool = True
    include_areas: bool = True
    include_interfaces: bool = True
    include_edges: bool = True


class BatfishBgpFactsQueryRequest(BaseModel):
    """Ad-hoc counterpart of the batfish-bgp-facts step's config fields."""

    network: str = Field(..., min_length=1)
    snapshot: str | None = None
    nodes: str | None = None
    include_process: bool = True
    include_peers: bool = True
    include_sessions: bool = True
    include_edges: bool = True


class BatfishNodePropertiesQueryRequest(BaseModel):
    """Ad-hoc counterpart of the batfish-node-properties step's config fields."""

    network: str = Field(..., min_length=1)
    snapshot: str | None = None
    nodes: str | None = None
    properties: str | None = None


class BatfishInterfacePropertiesQueryRequest(BaseModel):
    """Ad-hoc counterpart of the batfish-interface-properties step's config fields."""

    network: str = Field(..., min_length=1)
    snapshot: str | None = None
    nodes: str | None = None
    interfaces: str | None = None
    properties: str | None = None


class BatfishGenericQueryRequest(BaseModel):
    """Ad-hoc "custom question" counterpart -- any question in
    services.batfish.query_helpers.GENERIC_QUESTION_ALLOWLIST, with
    arbitrary params forwarded as pybatfish kwargs. `question` is a plain
    `str`, not the closed `BatfishQueryQuestion` Literal above -- the
    allow-list (checked service-side, in `query_generic`) is the actual
    validation, not the request schema.
    """

    network: str = Field(..., min_length=1)
    snapshot: str | None = None
    question: str = Field(..., min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)


class BatfishNetworksResponse(BaseModel):
    """Networks discovery -- lets a config panel populate a "network" dropdown
    instead of free text. See doc/BATFISH_INTEGRATION.md "Open items"."""

    networks: list[str]


class BatfishSnapshotInfo(BaseModel):
    name: str
    created_at: str | None = None


class BatfishSnapshotsResponse(BaseModel):
    """Sorted most-recent-first by created_at (mirrors resolve_latest_snapshot_name's
    own sort key), so a picker's default/top entry is the latest snapshot."""

    snapshots: list[BatfishSnapshotInfo]


class BatfishQueryResponse(BaseModel):
    success: bool
    # str, not BatfishQueryQuestion -- this field is output-only/descriptive
    # (the 3 typed request models above keep their own Literal-constrained
    # `question`-equivalent unchanged); a generic ad-hoc query's question name
    # is validated against GENERIC_QUESTION_ALLOWLIST server-side instead, not
    # by this response field's type.
    question: str
    network: str
    snapshot: str
    rows: list[dict[str, Any]]
    reachable: bool | None = None
    action: str | None = None
    error: str | None = None
    # Populated only by extract-facts/ospf-facts/bgp-facts/node-properties/
    # interface-properties: {node_name: <that node's parsed payload>}. This
    # is the SAME shape device.parsed[output_key]["parsed"] holds for one
    # device at real workflow runtime -- unlike `rows` (a flat answer table,
    # used by routes/reachability/testFilters/generic, which never populate
    # any device's `parsed` -- see doc/BATFISH_INTEGRATION.md "Template
    # Editor integration" for why these two response shapes exist side by
    # side rather than one being reused for the other).
    facts_by_node: dict[str, Any] | None = None
