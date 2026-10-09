"""Secret Manager connection management models.

See doc/SECRET_MANAGER_INTEGRATION.md. ``backend_config`` is intentionally a
free-form dict rather than a discriminated Pydantic union at the request-model
layer — it is validated per-backend inside
``services.secret_manager.connection_service.SecretManagerConnectionService``
(``ValueError`` -> 400), matching how ``GitRepositoryService`` validates
business rules rather than the request model. Unknown top-level request fields
are rejected (422); unknown ``backend_config`` keys are rejected by the service.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SecretManagerBackend(StrEnum):
    OPENBAO = "openbao"
    INFISICAL = "infisical"


class SecretManagerConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=255, description="Unique connection name")
    backend: SecretManagerBackend = Field(..., description="Which secret manager this connects to")
    credential_name: str | None = Field(
        None,
        max_length=255,
        description=(
            "Name of a global 'generic' credential holding this connection's own auth "
            "material (username = role_id / client_id, password = secret_id / client_secret). "
            "SSH credentials are rejected."
        ),
    )
    verify_ssl: bool = Field(
        default=True,
        description="Verify TLS certificates (must be true outside development)",
    )
    is_active: bool = Field(default=True, description="Connection is active")
    description: str | None = Field(None, description="Connection description")
    backend_config: dict[str, Any] = Field(
        ...,
        description=(
            "Backend-specific config: openbao {addr, mount, namespace}; "
            "infisical {site_url, project_id, environment}"
        ),
    )


class SecretManagerConnectionUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=255)
    backend: SecretManagerBackend | None = None
    credential_name: str | None = Field(default=None, max_length=255)
    verify_ssl: bool | None = None
    is_active: bool | None = None
    description: str | None = None
    backend_config: dict[str, Any] | None = None


class SecretManagerConnectionResponse(BaseModel):
    id: int
    name: str
    backend: SecretManagerBackend
    credential_name: str | None = None
    verify_ssl: bool
    is_active: bool
    description: str | None = None
    backend_config: dict[str, Any]
    created_at: str
    updated_at: str


class SecretManagerConnectionListResponse(BaseModel):
    connections: list[SecretManagerConnectionResponse]
    total: int


class SecretManagerConnectionTestResponse(BaseModel):
    success: bool
    message: str
