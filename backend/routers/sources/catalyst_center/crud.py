"""CRUD + test-connection for configured Cisco Catalyst Center sources."""

from __future__ import annotations

import logging
import uuid

from fastapi import Depends, HTTPException, status

import service_factory
from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from core.safe_urls import UnsafeURLError
from dependencies import get_catalyst_center_source_config_service
from models.catalyst_center import (
    CatalystCenterSourceCreateRequest,
    CatalystCenterSourceListResponse,
    CatalystCenterSourceResponse,
    CatalystCenterSourceUpdateRequest,
    CatalystCenterTestConnectionRequest,
    CatalystCenterTestConnectionResponse,
)
from routers.source_crud_factory import build_source_crud_router
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterAuthError,
    CatalystCenterValidationError,
)
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.catalyst_center.source_config_service import (
    CatalystCenterSourceConfigService,
    CatalystCenterSourceConflictError,
    CatalystCenterSourceNotFoundError,
)
from services.credentials.source_credentials import SourceCredentialError

logger = logging.getLogger(__name__)

_ConfigService = Depends(get_catalyst_center_source_config_service)

router = build_source_crud_router(
    source_type="catalyst_center",
    display_name="Catalyst Center",
    permission_resource="sources.catalyst_center",
    tag="sources-catalyst-center",
    service_dependency=get_catalyst_center_source_config_service,
    create_model=CatalystCenterSourceCreateRequest,
    update_model=CatalystCenterSourceUpdateRequest,
    response_model=CatalystCenterSourceResponse,
    list_response_model=CatalystCenterSourceListResponse,
    not_found_error=CatalystCenterSourceNotFoundError,
    conflict_error=CatalystCenterSourceConflictError,
    validation_errors=(CatalystCenterValidationError,),
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
    request: CatalystCenterTestConnectionRequest,
    config: CatalystCenterSourceConfigService,
) -> CatalystCenterCredentials:
    try:
        if request.source_id:
            return config.resolve_credentials(request.source_id)
        return config.resolve_inline_credentials(
            url=request.url or "",
            credential_id=int(request.credential_id or 0),
            verify_ssl=request.verify_ssl,
            timeout=request.timeout,
        )
    except CatalystCenterSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (CatalystCenterValidationError, UnsafeURLError, SourceCredentialError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/test-connection",
    response_model=CatalystCenterTestConnectionResponse,
    dependencies=[Depends(require_permission("sources.catalyst_center", "write"))],
)
async def test_connection(
    request: CatalystCenterTestConnectionRequest,
    _: User = Depends(get_current_user),
    config: CatalystCenterSourceConfigService = _ConfigService,
) -> CatalystCenterTestConnectionResponse:
    """Test connectivity using a saved ``source_id`` or inline dialog values."""
    credentials = _resolve_test_credentials(request, config)
    device_service = service_factory.build_catalyst_center_device_service(credentials)
    try:
        version = await device_service.test_connection()
        return CatalystCenterTestConnectionResponse(
            success=True, message="Connection successful", release=version
        )
    except CatalystCenterValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (CatalystCenterAuthError, CatalystCenterAPIError) as exc:
        error_id = uuid.uuid4()
        logger.warning("Catalyst Center test connection failed (error_id=%s): %s", error_id, exc)
        return CatalystCenterTestConnectionResponse(
            success=False,
            message=(
                f"Connection failed (ref: {error_id}). "
                "Check the credentials, URL and network reachability."
            ),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Catalyst Center test connection failed: ", exc)
