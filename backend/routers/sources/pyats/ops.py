"""pyATS shim connectivity check.

Two-stage check: first confirms the shim's HTTP layer is reachable
(``/health``), then confirms pyATS/Genie is actually functional inside the
container (``/health/pyats``) -- distinct failure messages for each stage.

Accepts either a saved ``source_id`` or fully inline ``{url, credential_id}``
values so the source dialog can test a connection before it is saved.
"""

from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, status

import service_factory
from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from core.safe_urls import UnsafeURLError
from dependencies import get_pyats_source_config_service
from models.pyats import PyATSTestConnectionRequest, PyATSTestConnectionResponse
from services.credentials.source_credentials import SourceCredentialError
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from services.pyats.credentials import PyATSCredentials
from services.pyats.source_config_service import (
    PyATSSourceConfigService,
    PyATSSourceNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sources/pyats",
    tags=["sources-pyats"],
    dependencies=[Depends(require_permission("sources.pyats", "read"))],
)


def _resolve_credentials(
    request: PyATSTestConnectionRequest,
    config: PyATSSourceConfigService,
) -> PyATSCredentials:
    try:
        if request.source_id:
            return config.resolve_credentials(request.source_id)
        return config.resolve_inline_credentials(
            url=request.url or "",
            credential_id=int(request.credential_id or 0),
            verify_ssl=request.verify_ssl,
            timeout=request.timeout,
        )
    except PyATSSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (PyATSValidationError, UnsafeURLError, SourceCredentialError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/test-connection",
    response_model=PyATSTestConnectionResponse,
    dependencies=[Depends(require_permission("sources.pyats", "write"))],
)
async def test_connection(
    request: PyATSTestConnectionRequest,
    _: User = Depends(get_current_user),
    config: PyATSSourceConfigService = Depends(get_pyats_source_config_service),
) -> PyATSTestConnectionResponse:
    credentials = _resolve_credentials(request, config)
    shim = service_factory.get_pyats_app_service()

    try:
        await shim.check_health(credentials)
    except PyATSAPIError as exc:
        error_id = uuid.uuid4()
        logger.warning("pyATS shim health check failed (error_id=%s): %s", error_id, exc)
        return PyATSTestConnectionResponse(
            success=False,
            message=f"pyATS shim is not reachable (ref: {error_id}).",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "pyATS shim health check failed: ", exc)

    try:
        pyats_health = await shim.check_pyats_health(credentials)
    except PyATSAPIError as exc:
        error_id = uuid.uuid4()
        logger.warning("pyATS functional check failed (error_id=%s): %s", error_id, exc)
        return PyATSTestConnectionResponse(
            success=False,
            message=f"Shim reachable, but the pyATS functional check failed (ref: {error_id}).",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "pyATS functional check failed: ", exc)

    if pyats_health.get("status") != "ok":
        return PyATSTestConnectionResponse(
            success=False,
            message="Shim reachable, but pyATS is not functioning correctly inside the container.",
        )

    pyats_version = pyats_health.get("pyats_version", "unknown")
    genie_version = pyats_health.get("genie_version", "unknown")
    return PyATSTestConnectionResponse(
        success=True,
        message=f"Connection successful (pyATS {pyats_version}, Genie {genie_version})",
    )
