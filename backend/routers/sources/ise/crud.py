"""CRUD for configured Cisco ISE sources (connection settings + credential)."""

from __future__ import annotations

import logging
import uuid

from fastapi import Depends, HTTPException, status

import service_factory
from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from core.safe_urls import UnsafeURLError
from dependencies import get_ise_source_config_service
from models.ise import (
    ISESourceCreateRequest,
    ISESourceListResponse,
    ISESourceResponse,
    ISESourceUpdateRequest,
    ISETestConnectionRequest,
    ISETestConnectionResponse,
)
from routers.source_crud_factory import build_source_crud_router
from services.credentials.source_credentials import SourceCredentialError
from services.ise.common.exceptions import ISEAPIError, ISEValidationError
from services.ise.credentials import ISECredentials
from services.ise.source_config_service import (
    ISESourceConfigService,
    ISESourceConflictError,
    ISESourceNotFoundError,
)

logger = logging.getLogger(__name__)

router = build_source_crud_router(
    source_type="ise",
    display_name="ISE",
    permission_resource="sources.ise",
    tag="sources-ise",
    service_dependency=get_ise_source_config_service,
    create_model=ISESourceCreateRequest,
    update_model=ISESourceUpdateRequest,
    response_model=ISESourceResponse,
    list_response_model=ISESourceListResponse,
    not_found_error=ISESourceNotFoundError,
    conflict_error=ISESourceConflictError,
    validation_errors=(ISEValidationError,),
    create_kwargs=lambda r: {
        "source_id": r.source_id,
        "url": r.url,
        "credential_id": r.credential_id,
        "verify_ssl": r.verify_ssl,
        "timeout": r.timeout,
    },
    update_kwargs=lambda r: {
        "url": r.url,
        "credential_id": r.credential_id,
        "verify_ssl": r.verify_ssl,
        "timeout": r.timeout,
    },
)


def _resolve_test_credentials(
    request: ISETestConnectionRequest,
    config: ISESourceConfigService,
) -> ISECredentials:
    try:
        if request.source_id:
            return config.resolve_credentials(request.source_id)
        return config.resolve_inline_credentials(
            url=request.url or "",
            credential_id=int(request.credential_id or 0),
            verify_ssl=request.verify_ssl,
            timeout=request.timeout,
        )
    except ISESourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ISEValidationError, UnsafeURLError, SourceCredentialError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/test-connection",
    response_model=ISETestConnectionResponse,
    dependencies=[Depends(require_permission("sources.ise", "write"))],
)
async def test_connection(
    request: ISETestConnectionRequest,
    _: User = Depends(get_current_user),
    config: ISESourceConfigService = Depends(get_ise_source_config_service),
) -> ISETestConnectionResponse:
    """Test ISE connectivity using a saved ``source_id`` or inline dialog values."""
    credentials = _resolve_test_credentials(request, config)
    device_service = service_factory.build_ise_network_device_service(credentials)
    try:
        await device_service.test_connection()
        return ISETestConnectionResponse(success=True, message="Connection successful")
    except ISEValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ISEAPIError as exc:
        error_id = uuid.uuid4()
        logger.warning("ISE test connection failed (error_id=%s): %s", error_id, exc)
        return ISETestConnectionResponse(
            success=False,
            message=(
                f"Connection failed (ref: {error_id}). "
                "Check the source configuration and network reachability."
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "ISE test connection failed: ", exc)
