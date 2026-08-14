"""Update Content step editor APIs."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from core.auth import get_current_user, require_permission
from core.models.users import User
from core.safe_http_errors import raise_internal_server_error
from models.update_content import UpdateContentProbeRequest, UpdateContentProbeResponse
from services.workflow_context.attribute_regex import (
    RegexFlagsConfig,
    apply_regex_content_replace,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workflow-steps/update-content",
    tags=["workflow-steps"],
    dependencies=[
        Depends(get_current_user),
        Depends(require_permission("workflow_steps", "read")),
    ],
)


@router.post("/probe", response_model=UpdateContentProbeResponse)
async def probe_content_replace(
    request: UpdateContentProbeRequest,
    _: User = Depends(get_current_user),
) -> UpdateContentProbeResponse:
    try:
        updated_text, match_count = apply_regex_content_replace(
            source_text=request.sample_text,
            pattern=request.pattern,
            replacement=request.replacement,
            flags=RegexFlagsConfig.from_mapping(request.regex_flags.model_dump()),
            replace_all=request.replace_all,
        )
        return UpdateContentProbeResponse(
            matched=match_count > 0,
            match_count=match_count,
            updated_text=updated_text,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to probe update-content regex: ", exc)
