"""Unauthenticated inbound webhooks.

The only non-proxy, non-JWT entry point in the API. ``POST /webhooks/git/{id}``
is protected solely by HMAC / shared-secret verification, per-repo+IP rate
limiting, replay dedup, and fail-closed-on-missing-secret — all in
``GitWebhookService``. See ``doc/CICD_PIPELINE.md`` §3.5 and §4.5.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from core.client_ip import resolve_client_host
from core.database import get_db
from services.change_requests.webhook_service import GitWebhookService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# A push event is a few KiB. The endpoint is unauthenticated, so the body is bounded as it
# streams in (a chunked request has no Content-Length for the global limit to look at, S4-11).
MAX_WEBHOOK_BODY_BYTES = 256 * 1024


async def _read_limited(request: Request, limit: int) -> bytes:
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Request body too large"
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/git/{git_repository_id}")
async def git_webhook(
    git_repository_id: int,
    request: Request,
    db: Session = Depends(get_db),
) -> JSONResponse:
    raw_body = await _read_limited(request, MAX_WEBHOOK_BODY_BYTES)
    status_code, body = GitWebhookService(db).process(
        git_repository_id=git_repository_id,
        raw_body=raw_body,
        headers=dict(request.headers),
        client_host=resolve_client_host(request),
    )
    return JSONResponse(status_code=status_code, content=body)
