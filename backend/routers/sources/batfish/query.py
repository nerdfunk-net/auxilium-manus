"""Ad-hoc Batfish query endpoints for the Template Editor's Options modal.

Runs a Batfish question directly against a configured source +
network(+snapshot), with no WorkflowRun involved. Two groups, matching
BatfishPreviewService's own split: routes/reachability/testFilters/generic
are the ad-hoc counterpart to the batfish-routing-table/batfish-path-check/
batfish-acl-check workflow steps (flat `rows`); extract-facts/ospf-facts/
bgp-facts/node-properties/interface-properties are the ad-hoc counterpart to
the per-device "facts" steps (`facts_by_node`, matching real runtime
`device.parsed[output_key]["parsed"]` shape). See
services.batfish.preview_service.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from dependencies import get_batfish_preview_service
from models.batfish import (
    BatfishBgpFactsQueryRequest,
    BatfishExtractFactsQueryRequest,
    BatfishGenericQueryRequest,
    BatfishInterfacePropertiesQueryRequest,
    BatfishNodePropertiesQueryRequest,
    BatfishOspfFactsQueryRequest,
    BatfishQueryResponse,
    BatfishReachabilityQueryRequest,
    BatfishRoutesQueryRequest,
    BatfishTestFiltersQueryRequest,
)
from services.batfish.common.exceptions import BatfishAPIError, BatfishValidationError
from services.batfish.preview_service import BatfishPreviewService
from services.batfish.source_config_service import BatfishSourceNotFoundError

logger = logging.getLogger(__name__)

# `query`, not `read`: these endpoints answer questions against any network
# on the coordinator, regardless of which workflow built it (B2). The
# read-only `viewer` role holds `sources.batfish:read` (source list, network
# and snapshot names) but not this.
router = APIRouter(
    prefix="/sources/batfish",
    tags=["sources-batfish"],
    dependencies=[Depends(require_permission("sources.batfish", "query"))],
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


@router.post("/{source_id}/query/generic", response_model=BatfishQueryResponse)
async def query_batfish_generic(
    source_id: str,
    request: BatfishGenericQueryRequest,
    _: User = Depends(get_current_user),
    service: BatfishPreviewService = Depends(get_batfish_preview_service),
) -> BatfishQueryResponse:
    """Ad-hoc counterpart to the "Custom Question..." Options-modal tab --
    any question in GENERIC_QUESTION_ALLOWLIST, not just the 3 typed ones
    above. A non-allow-listed question name is a ValueError from
    query_generic, mapped to 400 below like every other validation error --
    the allow-list rejection is deliberately not distinguished from a
    "missing required field" 400, so it carries no more information to a
    caller than "this request is invalid."
    """
    try:
        return await service.run_generic(source_id, request)
    except BatfishSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (BatfishValidationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except BatfishAPIError as exc:
        raise_internal_server_error(
            logger,
            "Batfish generic query failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Batfish generic query failed: ", exc)


@router.post("/{source_id}/query/extract-facts", response_model=BatfishQueryResponse)
async def query_batfish_extract_facts(
    source_id: str,
    request: BatfishExtractFactsQueryRequest,
    _: User = Depends(get_current_user),
    service: BatfishPreviewService = Depends(get_batfish_preview_service),
) -> BatfishQueryResponse:
    try:
        return await service.run_extract_facts(source_id, request)
    except BatfishSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (BatfishValidationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except BatfishAPIError as exc:
        raise_internal_server_error(
            logger,
            "Batfish extract facts query failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Batfish extract facts query failed: ", exc)


@router.post("/{source_id}/query/ospf-facts", response_model=BatfishQueryResponse)
async def query_batfish_ospf_facts(
    source_id: str,
    request: BatfishOspfFactsQueryRequest,
    _: User = Depends(get_current_user),
    service: BatfishPreviewService = Depends(get_batfish_preview_service),
) -> BatfishQueryResponse:
    try:
        return await service.run_ospf_facts(source_id, request)
    except BatfishSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (BatfishValidationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except BatfishAPIError as exc:
        raise_internal_server_error(
            logger,
            "Batfish OSPF facts query failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Batfish OSPF facts query failed: ", exc)


@router.post("/{source_id}/query/bgp-facts", response_model=BatfishQueryResponse)
async def query_batfish_bgp_facts(
    source_id: str,
    request: BatfishBgpFactsQueryRequest,
    _: User = Depends(get_current_user),
    service: BatfishPreviewService = Depends(get_batfish_preview_service),
) -> BatfishQueryResponse:
    try:
        return await service.run_bgp_facts(source_id, request)
    except BatfishSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (BatfishValidationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except BatfishAPIError as exc:
        raise_internal_server_error(
            logger,
            "Batfish BGP facts query failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Batfish BGP facts query failed: ", exc)


@router.post("/{source_id}/query/node-properties", response_model=BatfishQueryResponse)
async def query_batfish_node_properties(
    source_id: str,
    request: BatfishNodePropertiesQueryRequest,
    _: User = Depends(get_current_user),
    service: BatfishPreviewService = Depends(get_batfish_preview_service),
) -> BatfishQueryResponse:
    try:
        return await service.run_node_properties(source_id, request)
    except BatfishSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (BatfishValidationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except BatfishAPIError as exc:
        raise_internal_server_error(
            logger,
            "Batfish node properties query failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Batfish node properties query failed: ", exc)


@router.post("/{source_id}/query/interface-properties", response_model=BatfishQueryResponse)
async def query_batfish_interface_properties(
    source_id: str,
    request: BatfishInterfacePropertiesQueryRequest,
    _: User = Depends(get_current_user),
    service: BatfishPreviewService = Depends(get_batfish_preview_service),
) -> BatfishQueryResponse:
    try:
        return await service.run_interface_properties(source_id, request)
    except BatfishSourceNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (BatfishValidationError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except BatfishAPIError as exc:
        raise_internal_server_error(
            logger,
            "Batfish interface properties query failed: ",
            exc,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Batfish interface properties query failed: ", exc)
