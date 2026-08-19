"""Mattermost connectivity check, per configured source.

``GET /api/v4/users/me`` doubles as both a reachability and an auth check,
so this is a single-stage check (unlike the pyATS shim's two-stage check).
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
from dependencies import get_mattermost_source_config_service
from models.mattermost import MattermostSourceUpdateRequest, MattermostTestConnectionResponse
from services.mattermost.common.exceptions import MattermostAPIError, MattermostValidationError
from services.mattermost.credentials import MattermostCredentials
from services.mattermost.source_config_service import (
    MattermostSourceConfigService,
    MattermostSourceNotFoundError,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sources/mattermost/{source_id}",
    tags=["sources-mattermost"],
    dependencies=[Depends(require_permission("sources.mattermost", "read"))],
)


def _resolve_credentials(
    source_id: str,
    config: MattermostSourceConfigService,
    *,
    overrides: MattermostSourceUpdateRequest | None = None,
) -> MattermostCredentials:
    overrides = overrides or MattermostSourceUpdateRequest()
    try:
        return config.resolve_credentials(
            source_id,
            url=overrides.url,
            token=overrides.token,
            verify_ssl=overrides.verify_ssl,
            timeout=overrides.timeout,
        )
    except MattermostSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (MattermostValidationError, UnsafeURLError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/test-connection",
    response_model=MattermostTestConnectionResponse,
    dependencies=[Depends(require_permission("sources.mattermost", "write"))],
)
async def test_connection(
    source_id: str,
    overrides: MattermostSourceUpdateRequest | None = None,
    _: User = Depends(get_current_user),
    config: MattermostSourceConfigService = Depends(get_mattermost_source_config_service),
) -> MattermostTestConnectionResponse:
    """Test connectivity. ``overrides`` lets the source dialog validate unsaved
    edits (e.g. a token just typed in) against the live form values instead of
    only what's already persisted."""
    credentials = _resolve_credentials(source_id, config, overrides=overrides)
    client = service_factory.get_mattermost_app_service()

    try:
        me = await client.check_connection(credentials)
    except MattermostAPIError as exc:
        error_id = uuid.uuid4()
        logger.warning("Mattermost connection check failed (error_id=%s): %s", error_id, exc)
        return MattermostTestConnectionResponse(
            success=False,
            message=f"{exc} (ref: {error_id})",
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Mattermost connection check failed: ", exc)

    username = me.get("username", "unknown")
    return MattermostTestConnectionResponse(
        success=True,
        message=f"Connection successful (authenticated as '{username}')",
    )
