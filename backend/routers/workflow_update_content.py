"""Update Content step editor APIs."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from core.auth import get_current_user, require_permission
from core.models.users import User
from core.rate_limit import rate_limited
from core.regex_isolated import run_regex
from core.safe_http_errors import raise_internal_server_error
from models.update_content import UpdateContentProbeRequest, UpdateContentProbeResponse

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/workflow-steps/update-content",
    tags=["workflow-steps"],
    dependencies=[
        Depends(get_current_user),
        Depends(require_permission("workflow_steps", "read")),
    ],
)


@router.post(
    "/probe",
    response_model=UpdateContentProbeResponse,
    dependencies=[Depends(rate_limited("regex-probe", attempts=30, window_seconds=60))],
)
async def probe_content_replace(
    request: UpdateContentProbeRequest,
    _: User = Depends(get_current_user),
) -> UpdateContentProbeResponse:
    # The pattern is user-supplied: it runs in a killable child process (S4-07).
    try:
        outcome = await run_regex(
            {
                "op": "replace",
                "text": request.sample_text,
                "pattern": request.pattern,
                "replacement": request.replacement,
                "flags": request.regex_flags.model_dump(),
                "replace_all": request.replace_all,
            }
        )
        if not outcome.ok:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=outcome.error)
        return UpdateContentProbeResponse(
            matched=outcome.result["match_count"] > 0,
            match_count=outcome.result["match_count"],
            updated_text=outcome.result["updated_text"],
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to probe update-content regex: ", exc)
