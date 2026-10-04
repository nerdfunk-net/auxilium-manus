"""CRUD for configured Mattermost sources (connection settings + credential)."""

from __future__ import annotations

import logging

from dependencies import get_mattermost_source_config_service
from models.mattermost import (
    MattermostSourceCreateRequest,
    MattermostSourceListResponse,
    MattermostSourceResponse,
    MattermostSourceUpdateRequest,
)
from routers.source_crud_factory import build_source_crud_router
from services.mattermost.common.exceptions import MattermostValidationError
from services.mattermost.source_config_service import (
    MattermostSourceConflictError,
    MattermostSourceNotFoundError,
)

logger = logging.getLogger(__name__)

router = build_source_crud_router(
    source_type="mattermost",
    display_name="Mattermost",
    permission_resource="sources.mattermost",
    tag="sources-mattermost",
    service_dependency=get_mattermost_source_config_service,
    create_model=MattermostSourceCreateRequest,
    update_model=MattermostSourceUpdateRequest,
    response_model=MattermostSourceResponse,
    list_response_model=MattermostSourceListResponse,
    not_found_error=MattermostSourceNotFoundError,
    conflict_error=MattermostSourceConflictError,
    validation_errors=(MattermostValidationError,),
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
