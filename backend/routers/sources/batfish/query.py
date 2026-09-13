"""Ad-hoc Batfish query endpoints for the Template Editor's Options modal.

Runs a routes/reachability/testFilters question directly against a
configured source + network(+snapshot), with no WorkflowRun involved -- the
ad-hoc counterpart to the batfish-routing-table/batfish-path-check/
batfish-acl-check workflow steps. See services.batfish.preview_service.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_batfish_preview_service
from models.batfish import (
    BatfishQueryResponse,
    BatfishReachabilityQueryRequest,
    BatfishRoutesQueryRequest,
    BatfishTestFiltersQueryRequest,
)
from services.batfish.common.exceptions import BatfishAPIError, BatfishValidationError
from services.batfish.preview_service import BatfishPreviewService
from services.batfish.source_config_service import BatfishSourceNotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/sources/batfish",
    tags=["sources-batfish"],
    dependencies=[Depends(require_permission("sources.batfish", "read"))],
)


@router.post("/{source_id}/query/routes", response_model=BatfishQueryResponse)
async def query_batfish_routes(
    source_id: str,
    request: BatfishRoutesQueryRequest,
    _: User = Depends(get_current_user),
    service: BatfishPreviewService = Depends(get_batfish_preview_service),
) -> BatfishQueryResponse:
    try:
        return await service.run_routes(source_id, request)
    except BatfishSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (BatfishValidationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except BatfishAPIError as exc:
        raise_internal_server_error(
            logger,
            "Batfish routes query failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Batfish routes query failed: ", exc)


@router.post("/{source_id}/query/reachability", response_model=BatfishQueryResponse)
async def query_batfish_reachability(
    source_id: str,
    request: BatfishReachabilityQueryRequest,
    _: User = Depends(get_current_user),
    service: BatfishPreviewService = Depends(get_batfish_preview_service),
) -> BatfishQueryResponse:
    try:
        return await service.run_reachability(source_id, request)
    except BatfishSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (BatfishValidationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except BatfishAPIError as exc:
        raise_internal_server_error(
            logger,
            "Batfish reachability query failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Batfish reachability query failed: ", exc)


@router.post("/{source_id}/query/test-filters", response_model=BatfishQueryResponse)
async def query_batfish_test_filters(
    source_id: str,
    request: BatfishTestFiltersQueryRequest,
    _: User = Depends(get_current_user),
    service: BatfishPreviewService = Depends(get_batfish_preview_service),
) -> BatfishQueryResponse:
    try:
        return await service.run_test_filters(source_id, request)
    except BatfishSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (BatfishValidationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except BatfishAPIError as exc:
        raise_internal_server_error(
            logger,
            "Batfish ACL check query failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Batfish ACL check query failed: ", exc)
