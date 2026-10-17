"""CRUD for configured pyATS shim sources (connection settings + credential)."""

from __future__ import annotations

import logging

from dependencies import get_pyats_source_config_service
from models.pyats import (
    PyATSSourceCreateRequest,
    PyATSSourceListResponse,
    PyATSSourceResponse,
    PyATSSourceUpdateRequest,
)
from routers.source_crud_factory import build_source_crud_router
from services.pyats.common.exceptions import PyATSValidationError
from services.pyats.source_config_service import (
    PyATSSourceConflictError,
    PyATSSourceNotFoundError,
)

logger = logging.getLogger(__name__)

router = build_source_crud_router(
    source_type="pyats",
    display_name="pyATS",
    permission_resource="sources.pyats",
    tag="sources-pyats",
    service_dependency=get_pyats_source_config_service,
    create_model=PyATSSourceCreateRequest,
    update_model=PyATSSourceUpdateRequest,
    response_model=PyATSSourceResponse,
    list_response_model=PyATSSourceListResponse,
    not_found_error=PyATSSourceNotFoundError,
    conflict_error=PyATSSourceConflictError,
    validation_errors=(PyATSValidationError,),
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
