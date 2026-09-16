"""Resolve a ``SecretManagerConnection`` DB row into the config a client needs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from services.credentials.manager import CredentialManager


@dataclass(frozen=True)
class SecretManagerConnectionConfig:
    id: int
    name: str
    backend: str  # "openbao" | "infisical"
    verify_ssl: bool
    backend_config: dict[str, Any]
    # This connection's own resolved auth material: (role_id/client_id,
    # secret_id/client_secret). Both empty when credential_name is unset.
    auth_id: str
    auth_secret: str


def load_connection_config(connection_id: int, db: Session) -> SecretManagerConnectionConfig:
    """Resolve a ``secret_manager_connections`` row (+ its own auth credential)
    into a config ready for a client adapter.

    Raises ``ValueError`` for a missing/inactive connection or an unusable
    credential — surfaced as a step config error, matching
    ``workflow_steps.common.git_repository_loader``.
    """
    from services.secret_manager.connection_service import SecretManagerConnectionService

    connection = SecretManagerConnectionService(db).get_connection(connection_id)
    if connection is None:
        raise ValueError(f"Secret manager connection {connection_id} not found")
    if not connection.get("is_active", True):
        raise ValueError(f"Secret manager connection '{connection['name']}' is not active")

    auth_id = ""
    auth_secret = ""
    credential_name = connection.get("credential_name")
    if credential_name:
        # Background/system-scoped, like git auth — global credentials only.
        try:
            secret = CredentialManager(db).generic(credential_name)
        except ValueError as exc:
            raise ValueError(
                f"Secret manager connection '{connection['name']}': {exc}"
            ) from exc
        auth_id = secret.username or ""
        auth_secret = secret.password

    return SecretManagerConnectionConfig(
        id=connection["id"],
        name=connection["name"],
        backend=connection["backend"],
        verify_ssl=connection.get("verify_ssl", True),
        backend_config=connection.get("backend_config") or {},
        auth_id=auth_id,
        auth_secret=auth_secret,
    )
