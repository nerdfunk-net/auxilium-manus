"""Secret manager connection CRUD service — manages the
``secret_manager_connections`` table in PostgreSQL.

Separate from ``SecretManagerService`` (actual secret read/write operations
against a resolved connection's live client). This service only manages the
database records, mirroring ``GitRepositoryService``.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.models import SecretManagerConnection
from repositories import SecretManagerConnectionRepository

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_VALID_BACKENDS = frozenset({"openbao", "infisical"})
_REQUIRED_BACKEND_CONFIG_KEYS: dict[str, tuple[str, ...]] = {
    "openbao": ("addr", "mount"),
    "infisical": ("site_url", "project_id", "environment"),
}


def _validate_backend_config(backend: str, backend_config: dict[str, Any]) -> None:
    if backend not in _VALID_BACKENDS:
        raise ValueError(f"Unknown secret manager backend: {backend!r}")
    required = _REQUIRED_BACKEND_CONFIG_KEYS[backend]
    missing = [key for key in required if not str(backend_config.get(key) or "").strip()]
    if missing:
        raise ValueError(
            f"backend_config for '{backend}' is missing required field(s): {', '.join(missing)}"
        )


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
            backend_config = dict(data.get("backend_config") or {})
            _validate_backend_config(backend, backend_config)

            new_connection = self._repo.create(
                db=self._db,
                name=data["name"],
                backend=backend,
                credential_name=data.get("credential_name"),
                verify_ssl=data.get("verify_ssl", True),
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

            # Validate the resulting backend+backend_config together, whichever
            # (or neither) of the two fields actually changed.
            if "backend" in update_kwargs or "backend_config" in update_kwargs:
                current = self._repo.get_by_id(connection_id, db=self._db)
                if current is None:
                    raise ValueError(f"Connection {connection_id} not found")
                backend = str(update_kwargs.get("backend", current.backend))
                backend_config = dict(
                    update_kwargs.get("backend_config", current.backend_config or {})
                )
                _validate_backend_config(backend, backend_config)

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
