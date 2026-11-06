"""CRUD + test-connection for configured Cisco ACI (APIC) sources."""

from __future__ import annotations

import logging
import uuid

from fastapi import Depends, HTTPException, status

import service_factory
from core.auth import get_current_user, require_permission
from core.models.users import User
from core.rate_limit import rate_limited
from core.safe_http_errors import raise_internal_server_error
from core.safe_urls import UnsafeURLError
from dependencies import get_aci_source_config_service
from models.aci import (
    AciSourceCreateRequest,
    AciSourceListResponse,
    AciSourceResponse,
    AciSourceUpdateRequest,
    AciTestConnectionRequest,
    AciTestConnectionResponse,
)
from routers.source_crud_factory import build_source_crud_router
from routers.sources.aci.resolve import resolve_saved_credentials
from services.aci.common.exceptions import AciAPIError, AciAuthError, AciValidationError
from services.aci.credentials import AciCredentials
from services.aci.source_config_service import (
    AciSourceConfigService,
    AciSourceConflictError,
    AciSourceNotFoundError,
)
from services.credentials.source_credentials import SourceCredentialError

logger = logging.getLogger(__name__)

_ConfigService = Depends(get_aci_source_config_service)

router = build_source_crud_router(
    source_type="aci",
    display_name="Cisco ACI",
    permission_resource="sources.aci",
    tag="sources-aci",
    service_dependency=get_aci_source_config_service,
    create_model=AciSourceCreateRequest,
    update_model=AciSourceUpdateRequest,
    response_model=AciSourceResponse,
    list_response_model=AciSourceListResponse,
    not_found_error=AciSourceNotFoundError,
    conflict_error=AciSourceConflictError,
    validation_errors=(AciValidationError,),
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
    request: AciTestConnectionRequest, config: AciSourceConfigService
) -> AciCredentials:
    if request.source_id:
        return resolve_saved_credentials(request.source_id, config)
    try:
        return config.resolve_inline_credentials(
            url=request.url or "",
            credential_id=int(request.credential_id or 0),
            verify_ssl=request.verify_ssl,
            timeout=request.timeout,
        )
    except (AciValidationError, UnsafeURLError, SourceCredentialError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/test-connection",
    response_model=AciTestConnectionResponse,
    dependencies=[
        Depends(require_permission("sources.aci", "write")),
        Depends(rate_limited("aci-test-connection", attempts=10, window_seconds=60)),
    ],
)
async def test_connection(
    request: AciTestConnectionRequest,
    _: User = Depends(get_current_user),
    config: AciSourceConfigService = _ConfigService,
) -> AciTestConnectionResponse:
    """Test connectivity using a saved ``source_id`` or inline dialog values."""
    credentials = _resolve_test_credentials(request, config)
    device_service = service_factory.build_aci_device_service(credentials)
    try:
        version = await device_service.test_connection()
        return AciTestConnectionResponse(
            success=True, message="Connection successful", version=version
        )
    except AciValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (AciAuthError, AciAPIError) as exc:
        error_id = uuid.uuid4()
        logger.warning("ACI test connection failed (error_id=%s): %s", error_id, exc)
        return AciTestConnectionResponse(
            success=False,
            message=(
                f"Connection failed (ref: {error_id}). "
                "Check the credentials, URL and network reachability."
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "ACI test connection failed: ", exc)
