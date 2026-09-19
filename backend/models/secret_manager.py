"""Secret Manager connection management models.

See doc/SECRET_MANAGER_INTEGRATION.md. ``backend_config`` is intentionally a
free-form dict rather than a discriminated Pydantic union at the request-model
layer — it is validated per-backend inside
``services.secret_manager.connection_service.SecretManagerConnectionService``
(``ValueError`` -> 400), matching how ``GitRepositoryService`` validates
business rules rather than the request model.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class SecretManagerBackend(StrEnum):
    OPENBAO = "openbao"
    INFISICAL = "infisical"


class OpenBaoConnectionConfig(BaseModel):
    """``backend_config`` shape for ``backend == "openbao"``."""

    addr: str = Field(..., description="OpenBao/Vault base URL, e.g. https://vault.internal:8200")
    mount: str = Field(..., description="KV v2 mount for this connection, e.g. manus-network")
    namespace: str | None = Field(None, description="OpenBao Enterprise namespace, if any")


class InfisicalConnectionConfig(BaseModel):
    """``backend_config`` shape for ``backend == "infisical"``."""

    site_url: str = Field(
        default="https://app.infisical.com", description="Infisical instance base URL"
    )
    project_id: str = Field(..., description="Infisical project (workspace) id")
    environment: str = Field(..., description="Infisical environment slug, e.g. prod")


class SecretManagerConnectionRequest(BaseModel):
    name: str = Field(..., description="Unique connection name")
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
            "Backend-specific config — see OpenBaoConnectionConfig / InfisicalConnectionConfig"
        ),
    )


class SecretManagerConnectionUpdateRequest(BaseModel):
    name: str | None = None
    backend: SecretManagerBackend | None = None
    credential_name: str | None = None
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
