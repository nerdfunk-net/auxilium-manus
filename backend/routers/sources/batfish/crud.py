"""CRUD for configured Batfish sources (host/port only -- no credential)."""

from __future__ import annotations

import logging

from dependencies import get_batfish_source_config_service
from models.batfish import (
    BatfishSourceCreateRequest,
    BatfishSourceListResponse,
    BatfishSourceResponse,
    BatfishSourceUpdateRequest,
)
from routers.source_crud_factory import build_source_crud_router
from services.batfish.common.exceptions import BatfishValidationError
from services.batfish.source_config_service import (
    BatfishSourceConflictError,
    BatfishSourceNotFoundError,
)

logger = logging.getLogger(__name__)

router = build_source_crud_router(
    source_type="batfish",
    display_name="Batfish",
    permission_resource="sources.batfish",
    tag="sources-batfish",
    service_dependency=get_batfish_source_config_service,
    create_model=BatfishSourceCreateRequest,
    update_model=BatfishSourceUpdateRequest,
    response_model=BatfishSourceResponse,
    list_response_model=BatfishSourceListResponse,
    not_found_error=BatfishSourceNotFoundError,
    conflict_error=BatfishSourceConflictError,
    validation_errors=(BatfishValidationError,),
    create_kwargs=lambda r: {"source_id": r.source_id, "host": r.host, "port": r.port},
    update_kwargs=lambda r: {"host": r.host, "port": r.port},
)
