"""Saved AI assistant conversations (doc/ai_integration/AI_ASSISTANT.md).

Gated by ``ai_assistant:use`` only, like the settings endpoints: the panel is hidden while the
assistant is switched off, but a user can still list and delete what they saved. Every row is
private to its owner; another user's conversation answers 404.
"""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from core.rate_limit import rate_limited
from models.ai_conversations import (
    AiConversationCreate,
    AiConversationDetail,
    AiConversationSummary,
    AiConversationUpdate,
    AiSurface,
)
from services.ai_assistant.conversation_service import AiConversationService
from services.ai_assistant.exceptions import (
    AiAssistantError,
    AiConversationLimitError,
    AiConversationNotFoundError,
    AiConversationTooLargeError,
)

router = APIRouter(prefix="/ai/conversations", tags=["ai-assistant"])

_USE = Depends(require_permission("ai_assistant", "use"))
_WRITE_BUDGET = rate_limited("ai-conversations", attempts=30, window_seconds=60)

_STATUS_FOR_ERROR: dict[type[AiAssistantError], int] = {
    AiConversationNotFoundError: status.HTTP_404_NOT_FOUND,
    AiConversationLimitError: status.HTTP_409_CONFLICT,
    AiConversationTooLargeError: status.HTTP_413_CONTENT_TOO_LARGE,
}


def get_conversation_service(db: Session = Depends(get_db)) -> AiConversationService:
    return AiConversationService.from_session(db)


def _raise_http(exc: AiAssistantError) -> NoReturn:
    code = _STATUS_FOR_ERROR.get(type(exc), status.HTTP_400_BAD_REQUEST)
    raise HTTPException(status_code=code, detail={"code": exc.code, "message": str(exc)}) from exc


@router.get("", response_model=list[AiConversationSummary], dependencies=[_USE])
def list_conversations(
    surface: AiSurface | None = None,
    subject_key: str | None = None,
    current_user: User = Depends(get_current_user),
    service: AiConversationService = Depends(get_conversation_service),
) -> list[AiConversationSummary]:
    return service.list(current_user.id, surface=surface, subject_key=subject_key)


@router.get("/{conversation_id}", response_model=AiConversationDetail, dependencies=[_USE])
def get_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    service: AiConversationService = Depends(get_conversation_service),
) -> AiConversationDetail:
    try:
        return service.get(current_user.id, conversation_id)
    except AiAssistantError as exc:
        _raise_http(exc)


@router.post(
    "",
    response_model=AiConversationDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[_USE, Depends(_WRITE_BUDGET)],
)
def create_conversation(
    body: AiConversationCreate,
    current_user: User = Depends(get_current_user),
    service: AiConversationService = Depends(get_conversation_service),
) -> AiConversationDetail:
    try:
        return service.create(current_user.id, body)
    except AiAssistantError as exc:
        _raise_http(exc)


@router.put(
    "/{conversation_id}",
    response_model=AiConversationDetail,
    dependencies=[_USE, Depends(_WRITE_BUDGET)],
)
def update_conversation(
    conversation_id: int,
    body: AiConversationUpdate,
    current_user: User = Depends(get_current_user),
    service: AiConversationService = Depends(get_conversation_service),
) -> AiConversationDetail:
    try:
        return service.update(current_user.id, conversation_id, body)
    except AiAssistantError as exc:
        _raise_http(exc)


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[_USE, Depends(_WRITE_BUDGET)],
)
def delete_conversation(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    service: AiConversationService = Depends(get_conversation_service),
) -> Response:
    try:
        service.delete(current_user.id, conversation_id)
    except AiAssistantError as exc:
        _raise_http(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
