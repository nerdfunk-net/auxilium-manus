"""Secret manager connection management router — CRUD + test-connection.

Actual secret read/write/generate operations happen only from workflow steps
(``secret-get``/``secret-set``/``secret-generate``) via ``SecretManagerService``,
never through this router — see doc/SECRET_MANAGER_INTEGRATION.md.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import service_factory
from core.auth import get_current_user, require_permission
from core.database import get_db
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_secret_manager_connection_service
from models.secret_manager import (
    SecretManagerConnectionListResponse,
    SecretManagerConnectionRequest,
    SecretManagerConnectionResponse,
    SecretManagerConnectionTestResponse,
    SecretManagerConnectionUpdateRequest,
)
from services.secret_manager.connection_service import SecretManagerConnectionService
from services.secret_manager.exceptions import SecretManagerError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/secret-manager/connections", tags=["secret-manager"])


@router.get(
    "",
    response_model=SecretManagerConnectionListResponse,
    dependencies=[Depends(require_permission("secret_manager.connections", "read"))],
)
def get_connections(
    active_only: bool = False,
    current_user: dict = Depends(get_current_user),
    connection_service: SecretManagerConnectionService = Depends(
        get_secret_manager_connection_service
    ),
):
    try:
        connections = connection_service.get_connections(active_only=active_only)
        responses = [SecretManagerConnectionResponse(**c) for c in connections]
        return SecretManagerConnectionListResponse(connections=responses, total=len(responses))
    except Exception as e:
        raise_internal_server_error(logger, "Internal error", e)


@router.get(
    "/{connection_id}",
    response_model=SecretManagerConnectionResponse,
    dependencies=[Depends(require_permission("secret_manager.connections", "read"))],
)
def get_connection(
    connection_id: int,
    current_user: dict = Depends(get_current_user),
    connection_service: SecretManagerConnectionService = Depends(
        get_secret_manager_connection_service
    ),
):
    try:
        connection = connection_service.get_connection(connection_id)
        if not connection:
            raise HTTPException(status_code=404, detail="Connection not found")
        return SecretManagerConnectionResponse(**connection)
    except HTTPException:
        raise
    except Exception as e:
        raise_internal_server_error(logger, "Internal error", e)


@router.post(
    "",
    response_model=SecretManagerConnectionResponse,
    dependencies=[Depends(require_permission("secret_manager.connections", "write"))],
)
def create_connection(
    request: SecretManagerConnectionRequest,
    current_user: dict = Depends(get_current_user),
    connection_service: SecretManagerConnectionService = Depends(
        get_secret_manager_connection_service
    ),
):
    try:
        connection_id = connection_service.create_connection(request.model_dump())
        created = connection_service.get_connection(connection_id)
        if not created:
            raise_internal_server_error(
                logger, f"Failed to retrieve created connection {connection_id}"
            )
        return SecretManagerConnectionResponse(**created)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise_internal_server_error(logger, "Internal error", e)


@router.put(
    "/{connection_id}",
    response_model=SecretManagerConnectionResponse,
    dependencies=[Depends(require_permission("secret_manager.connections", "write"))],
)
async def update_connection(
    connection_id: int,
    request: SecretManagerConnectionUpdateRequest,
    current_user: dict = Depends(get_current_user),
    connection_service: SecretManagerConnectionService = Depends(
        get_secret_manager_connection_service
    ),
):
    try:
        update_data = request.model_dump(exclude_unset=True)
        connection_service.update_connection(connection_id, update_data)
        updated = connection_service.get_connection(connection_id)
        if not updated:
            raise HTTPException(status_code=404, detail="Connection not found")
        # An edited connection may need a fresh client (new auth material,
        # new mount/project) — drop any cached one so the next use rebuilds it.
        await service_factory.get_secret_manager_registry().invalidate(connection_id)
        return SecretManagerConnectionResponse(**updated)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        raise_internal_server_error(logger, "Internal error", e)


@router.delete(
    "/{connection_id}",
    dependencies=[Depends(require_permission("secret_manager.connections", "delete"))],
)
async def delete_connection(
    connection_id: int,
    current_user: dict = Depends(get_current_user),
    connection_service: SecretManagerConnectionService = Depends(
        get_secret_manager_connection_service
    ),
):
    try:
        existing = connection_service.get_connection(connection_id)
        if not existing:
            raise HTTPException(status_code=404, detail="Connection not found")
        connection_service.delete_connection(connection_id)
        await service_factory.get_secret_manager_registry().invalidate(connection_id)
        return {"success": True, "message": f"Connection {connection_id} deleted"}
    except HTTPException:
        raise
    except Exception as e:
        raise_internal_server_error(logger, "Internal error", e)


@router.post(
    "/{connection_id}/test",
    response_model=SecretManagerConnectionTestResponse,
    dependencies=[Depends(require_permission("secret_manager.connections", "write"))],
)
async def test_connection(
    connection_id: int,
    current_user: dict = Depends(get_current_user),
    connection_service: SecretManagerConnectionService = Depends(
        get_secret_manager_connection_service
    ),
    db: Session = Depends(get_db),
):
    """Force a fresh login attempt against the configured backend."""
    connection = connection_service.get_connection(connection_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Connection not found")

    registry = service_factory.get_secret_manager_registry()
    await registry.invalidate(connection_id)
    try:
        await registry.get_or_create(connection_id, db)
    except (SecretManagerError, ValueError) as exc:
        return SecretManagerConnectionTestResponse(success=False, message=str(exc))
    except Exception as e:
        raise_internal_server_error(logger, "Internal error", e)
    return SecretManagerConnectionTestResponse(success=True, message="Connected successfully")
