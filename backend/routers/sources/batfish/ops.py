"""Batfish coordinator connectivity check.

Single-stage check -- unlike pyATS's shim, there's no separate "process is
up" vs "functionally working" distinction to make, since pybatfish has no
lightweight liveness probe of its own beyond a real RPC call
(``list_networks()``).

Accepts either a saved ``source_id`` or inline ``{host, port}`` values so the
source dialog can test a connection before it is saved.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

import service_factory
from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_batfish_source_config_service
from models.batfish import BatfishTestConnectionRequest, BatfishTestConnectionResponse
from services.batfish.common.exceptions import BatfishAPIError, BatfishValidationError
from services.batfish.credentials import BatfishConnection
from services.batfish.source_config_service import (
    BatfishSourceConfigService,
    BatfishSourceNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sources/batfish",
    tags=["sources-batfish"],
    dependencies=[Depends(require_permission("sources.batfish", "read"))],
)


def _resolve_connection(
    request: BatfishTestConnectionRequest,
    config: BatfishSourceConfigService,
) -> BatfishConnection:
    try:
        if request.source_id:
            return config.resolve_connection(request.source_id)
        return config.resolve_inline_connection(host=request.host or "", port=request.port)
    except BatfishSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BatfishValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/test-connection",
    response_model=BatfishTestConnectionResponse,
    dependencies=[Depends(require_permission("sources.batfish", "write"))],
)
async def test_connection(
    request: BatfishTestConnectionRequest,
    _: User = Depends(get_current_user),
    config: BatfishSourceConfigService = Depends(get_batfish_source_config_service),
) -> BatfishTestConnectionResponse:
    # _resolve_connection now does a DNS lookup (B1) -- off the event loop.
    connection = await asyncio.to_thread(_resolve_connection, request, config)
    batfish = service_factory.get_batfish_app_service()

    try:
        networks = await batfish.check_health(connection)
    except BatfishAPIError as exc:
        error_id = uuid.uuid4()
        logger.warning("Batfish health check failed (error_id=%s): %s", error_id, exc)
        return BatfishTestConnectionResponse(
            success=False,
            message=f"Batfish coordinator is not reachable (ref: {error_id}).",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Batfish health check failed: ", exc)

    return BatfishTestConnectionResponse(
        success=True,
        message=f"Connection successful ({len(networks)} network(s) on coordinator)",
    )
