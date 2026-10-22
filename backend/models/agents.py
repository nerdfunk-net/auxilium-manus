"""Pydantic models for agent source configuration."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from core.source_keys import SOURCE_ID_PATTERN

_ID_REGEX = SOURCE_ID_PATTERN.pattern

AgentTransportName = Literal["http", "redis"]


class AgentSourceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., pattern=_ID_REGEX, max_length=64)
    transport: AgentTransportName
    # Identity bound into every message and used in Redis key names / ACLs.
    agent_id: str = Field(..., pattern=_ID_REGEX, max_length=64)
    url: str | None = Field(default=None, max_length=2048)
    credential_id: int = Field(..., gt=0)
    max_concurrency: int = Field(default=4, ge=1, le=64)
    max_request_bytes: int = Field(default=1_048_576, ge=1_024, le=8 * 1_048_576)
    max_timeout_seconds: int = Field(default=60, ge=1, le=600)


class AgentSourceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transport: AgentTransportName | None = None
    agent_id: str | None = Field(default=None, pattern=_ID_REGEX, max_length=64)
    url: str | None = Field(default=None, max_length=2048)
    credential_id: int | None = Field(default=None, gt=0)
    max_concurrency: int | None = Field(default=None, ge=1, le=64)
    max_request_bytes: int | None = Field(default=None, ge=1_024, le=8 * 1_048_576)
    max_timeout_seconds: int | None = Field(default=None, ge=1, le=600)


class AgentSourceResponse(BaseModel):
    source_id: str
    transport: AgentTransportName
    agent_id: str
    url: str | None = None
    credential_id: int | None = None
    credential_name: str | None = None
    max_concurrency: int
    max_request_bytes: int
    max_timeout_seconds: int


class AgentSourceListResponse(BaseModel):
    sources: list[AgentSourceResponse]
    total: int


class AgentTestConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., min_length=1, max_length=64)


class AgentTestConnectionResponse(BaseModel):
    success: bool
    message: str
    latency_ms: int | None = None


class AgentStatusResponse(BaseModel):
    transport: AgentTransportName
    # None = unknown (HTTP agents have no heartbeat, or Redis could not be read).
    online: bool | None = None
    version: str | None = None
    handlers: list[str] = Field(default_factory=list)
    last_heartbeat: int | None = None
    message: str
