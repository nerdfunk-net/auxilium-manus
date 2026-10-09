"""Secret manager connection CRUD service — manages the
``secret_manager_connections`` table in PostgreSQL.

Separate from ``SecretManagerService`` (actual secret read/write operations
against a resolved connection's live client). This service only manages the
database records, mirroring ``GitRepositoryService``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.models import SecretManagerConnection
from repositories import SecretManagerConnectionRepository
from services.secret_manager.transport_policy import validate_connection_transport

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_VALID_BACKENDS = frozenset({"openbao"})
_REQUIRED_BACKEND_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "openbao": ("addr", "mount"),
}
_OPTIONAL_BACKEND_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "openbao": ("namespace",),
}
_MAX_BACKEND_CONFIG_VALUE_LENGTH = 255
_TRANSPORT_FIELDS = frozenset({"backend", "backend_config", "verify_ssl"})


@dataclass(frozen=True)
class SecretManagerConnectionGeneration:
    """Cache key for ``SecretManagerClientRegistry`` (SM4).

    ``updated_at`` is the ORM datetime, not the ISO string ``_to_dict`` emits.
    """

    name: str
    is_active: bool
    updated_at: datetime


def _validate_backend_config(backend: str, backend_config: dict[str, Any]) -> None:
    if backend not in _VALID_BACKENDS:
        raise ValueError(f"Unknown secret manager backend: {backend!r}")
    required = _REQUIRED_BACKEND_CONFIG_KEYS[backend]
    missing = [key for key in required if not str(backend_config.get(key) or "").strip()]
    if missing:
        raise ValueError(
            f"backend_config for '{backend}' is missing required field(s): {', '.join(missing)}"
        )
    allowed = set(required) | set(_OPTIONAL_BACKEND_CONFIG_KEYS[backend])
    unknown = sorted(set(backend_config) - allowed)
    if unknown:
        raise ValueError(
            f"backend_config for '{backend}' has unknown field(s): {', '.join(unknown)}"
        )
    for key, value in backend_config.items():
        if not isinstance(value, str) or len(value) > _MAX_BACKEND_CONFIG_VALUE_LENGTH:
            raise ValueError(
                f"backend_config.{key} must be a string of at most "
                f"{_MAX_BACKEND_CONFIG_VALUE_LENGTH} characters"
            )


def _validate_connection(
    backend: str, backend_config: dict[str, Any], verify_ssl: bool
) -> dict[str, Any]:
    """Shape check + transport policy (SM2). Returns backend_config with the
    URL field normalized by ``validate_outbound_http_url``."""
    # An explicit null (e.g. namespace) means "absent".
    backend_config = {k: v for k, v in backend_config.items() if v is not None}
    _validate_backend_config(backend, backend_config)
    safe_url = validate_connection_transport(
        backend=backend,
        backend_config=backend_config,
        verify_ssl=verify_ssl,
        resolve_dns=True,
    )
    return {**backend_config, "addr": safe_url}


class SecretManagerConnectionService:
    """CRUD service for secret manager connections in PostgreSQL."""

    def __init__(self, db: Session | None = None) -> None:
        self._db = db
        self._repo = SecretManagerConnectionRepository(db)

    def create_connection(self, data: dict[str, Any]) -> int:
        try:
            if self._repo.name_exists(data["name"], db=self._db):
                raise ValueError(f"Connection with name '{data['name']}' already exists")

            backend = str(data["backend"])
            verify_ssl = bool(data.get("verify_ssl", True))
            backend_config = _validate_connection(
                backend, dict(data.get("backend_config") or {}), verify_ssl
            )

            new_connection = self._repo.create(
                db=self._db,
                name=data["name"],
                backend=backend,
                credential_name=data.get("credential_name"),
                verify_ssl=verify_ssl,
                is_active=data.get("is_active", True),
                backend_config=backend_config,
                description=data.get("description"),
            )
            logger.info(
                "Created secret manager connection: %s (ID: %s)", data["name"], new_connection.id
            )
            return new_connection.id
        except ValueError:
            raise
        except Exception as e:
            logger.error("Error creating secret manager connection: %s", e)
            raise

    def get_connection(self, connection_id: int) -> dict[str, Any] | None:
        try:
            connection = self._repo.get_by_id(connection_id, db=self._db)
            return self._to_dict(connection) if connection else None
        except Exception as e:
            logger.error("Error getting secret manager connection %s: %s", connection_id, e)
            raise

    def get_generation(self, connection_id: int) -> SecretManagerConnectionGeneration | None:
        """Return the cache-key columns for *connection_id*, always from the DB.

        ``None`` means the row is gone (deleted). Used by
        ``SecretManagerClientRegistry.get_or_create`` so worker processes notice
        edits, deactivations, and deletes without a cross-process invalidate.
        """
        connection = self._repo.get_by_id_fresh(connection_id, db=self._db)
        if connection is None:
            return None
        return SecretManagerConnectionGeneration(
            name=str(connection.name),
            is_active=bool(connection.is_active),
            updated_at=connection.updated_at,
        )

    def get_connections(self, active_only: bool = False) -> list[dict[str, Any]]:
        try:
            connections = (
                self._repo.get_all_active(db=self._db)
                if active_only
                else self._repo.get_all(db=self._db)
            )
            return [self._to_dict(c) for c in connections]
        except Exception as e:
            logger.error("Error getting secret manager connections: %s", e)
            raise

    def update_connection(self, connection_id: int, data: dict[str, Any]) -> bool:
        try:
            valid_fields = [
                "name",
                "backend",
                "credential_name",
                "verify_ssl",
                "is_active",
                "backend_config",
                "description",
            ]
            update_kwargs = {k: v for k, v in data.items() if k in valid_fields}
            if not update_kwargs:
                return False

            if "name" in update_kwargs:
                existing = self._repo.get_by_name(update_kwargs["name"], db=self._db)
                if existing and existing.id != connection_id:
                    raise ValueError(
                        f"Connection with name '{update_kwargs['name']}' already exists"
                    )

            # Validate the resulting backend+backend_config+verify_ssl together,
            # whichever (or none) of the three actually changed (SM2).
            if _TRANSPORT_FIELDS & update_kwargs.keys():
                current = self._repo.get_by_id(connection_id, db=self._db)
                if current is None:
                    raise ValueError(f"Connection {connection_id} not found")
                backend = str(update_kwargs.get("backend", current.backend))
                backend_config = dict(
                    update_kwargs.get("backend_config", current.backend_config or {})
                )
                verify_ssl = bool(update_kwargs.get("verify_ssl", current.verify_ssl))
                update_kwargs["backend_config"] = _validate_connection(
                    backend, backend_config, verify_ssl
                )

            update_kwargs["updated_at"] = datetime.now(UTC)
            self._repo.update(connection_id, db=self._db, **update_kwargs)
            logger.info("Updated secret manager connection ID: %s", connection_id)
            return True
        except ValueError:
            raise
        except Exception as e:
            logger.error("Error updating secret manager connection %s: %s", connection_id, e)
            raise

    def delete_connection(self, connection_id: int) -> bool:
        try:
            self._repo.delete(connection_id, db=self._db)
            logger.info("Deleted secret manager connection ID: %s", connection_id)
            return True
        except Exception as e:
            logger.error("Error deleting secret manager connection %s: %s", connection_id, e)
            raise

    def _to_dict(self, connection: SecretManagerConnection) -> dict[str, Any]:
        return {
            "id": connection.id,
            "name": connection.name,
            "backend": connection.backend,
            "credential_name": connection.credential_name,
            "verify_ssl": connection.verify_ssl,
            "is_active": connection.is_active,
            "backend_config": connection.backend_config or {},
            "description": connection.description,
            "created_at": connection.created_at.isoformat() if connection.created_at else None,
            "updated_at": connection.updated_at.isoformat() if connection.updated_at else None,
        }
