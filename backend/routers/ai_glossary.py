"""Admin API for the inventory assistant glossary (doc/ai_integration/AI_ASSISTANT.md, "Glossary").

The text of an entry steers what the model asks Nautobot, so writes and reads are admin-only
(doc/claude/auth.md P3). The assistant itself reads entries through the ``get_glossary`` tool.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_role
from core.database import get_db
from core.models.users import User
from core.rate_limit import rate_limited
from models.ai_glossary import (
    GlossaryListResponse,
    GlossaryTermCreate,
    GlossaryTermResponse,
    GlossaryTermUpdate,
)
from routers.ai_assistant import require_operator_enabled
from services.ai_assistant.glossary_service import GlossaryService
from services.ai_assistant.inventory_reader import DbInventoryReader

router = APIRouter(prefix="/ai/glossary", tags=["ai-glossary"])

_GATE = [Depends(require_operator_enabled), Depends(require_role("admin"))]
_WRITE_BUDGET = rate_limited("ai-glossary", attempts=30, window_seconds=60)


@router.get("", response_model=GlossaryListResponse, dependencies=_GATE)
def list_terms(
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> GlossaryListResponse:
    return GlossaryService(db).list_terms(q, limit, offset)


@router.post(
    "",
    response_model=GlossaryTermResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[*_GATE, Depends(_WRITE_BUDGET)],
)
async def create_term(
    body: GlossaryTermCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GlossaryTermResponse:
    reader = DbInventoryReader(current_user.id, current_user.username, body.source_id)
    return await GlossaryService(db).create(body, reader, current_user.id)


@router.put(
    "/{term_id}",
    response_model=GlossaryTermResponse,
    dependencies=[*_GATE, Depends(_WRITE_BUDGET)],
)
async def update_term(
    term_id: int,
    body: GlossaryTermUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> GlossaryTermResponse:
    reader = DbInventoryReader(current_user.id, current_user.username, body.source_id)
    return await GlossaryService(db).update(term_id, body, reader, current_user.id)


@router.delete(
    "/{term_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[*_GATE, Depends(_WRITE_BUDGET)],
)
def delete_term(
    term_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    GlossaryService(db).delete(term_id, current_user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
