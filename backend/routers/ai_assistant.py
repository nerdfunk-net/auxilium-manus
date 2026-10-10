"""In-app AI assistant API (doc/ai_integration/AI_ASSISTANT.md).

``GET /ai/status`` is open to any signed-in user so the UI can decide whether to render
assistant surfaces. Everything else requires ``ai_assistant:use``. The enable switch is
enforced here on the server for chat; hiding the UI is only a convenience. The one deliberate
exception is ``POST /ai/settings/test``, which works while the assistant is off so a user can
verify a key before switching it on (it is still permission-gated and rate limited).
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission
from core.database import get_db
from core.models.users import User
from core.rate_limit import rate_limited
from models.ai_assistant import (
    AiStatusResponse,
    ChatRequest,
    InventoryContext,
    RunViewerContext,
    TemplateEditorContext,
    UserAiSettingsResponse,
    UserAiSettingsUpdate,
    WorkflowCanvasContext,
)
from services.ai_assistant.chat_service import ChatEvent, check_connection, stream_chat
from services.ai_assistant.exceptions import (
    AiAssistantDisabledError,
    AiAssistantError,
    AiAssistantNotConfiguredError,
    AiSettingsValidationError,
)
from services.ai_assistant.inventory_reader import DbInventoryReader
from services.ai_assistant.prompts import BASE_SYSTEM_PROMPT
from services.ai_assistant.providers.base import ChatMessage
from services.ai_assistant.run_reader import DbRunReader
from services.ai_assistant.settings_service import AiRuntimeConfig, AiSettingsService
from services.ai_assistant.surfaces import (
    AssistantSession,
    build_inventory_session,
    build_run_viewer_session,
    build_template_editor_session,
    build_workflow_editor_session,
)
from services.ai_assistant.template_reader import DbTemplateReader
from services.ai_assistant.tools.base import Toolbox
from services.ai_assistant.workflow_reader import DbReferenceReader, DbWorkflowValidator
from services.auth.rbac_service import RBACService

router = APIRouter(prefix="/ai", tags=["ai-assistant"])

_USE = Depends(require_permission("ai_assistant", "use"))

# Chat is the expensive path (an outbound LLM call per request); the test is a cheap probe
# but still spends the user's own quota, so it gets a much smaller budget.
_CHAT_BUDGET = rate_limited("ai-chat", attempts=30, window_seconds=60)
_TEST_BUDGET = rate_limited("ai-test", attempts=6, window_seconds=60)

_STATUS_FOR_ERROR: dict[type[AiAssistantError], int] = {
    AiAssistantDisabledError: status.HTTP_403_FORBIDDEN,
    AiAssistantNotConfiguredError: status.HTTP_409_CONFLICT,
    AiSettingsValidationError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def get_ai_settings_service(db: Session = Depends(get_db)) -> AiSettingsService:
    return AiSettingsService.from_session(db)


def _raise_http(exc: AiAssistantError) -> NoReturn:
    code = _STATUS_FOR_ERROR.get(type(exc), status.HTTP_400_BAD_REQUEST)
    raise HTTPException(status_code=code, detail={"code": exc.code, "message": str(exc)}) from exc


def _session_for(
    context: TemplateEditorContext | WorkflowCanvasContext | RunViewerContext | InventoryContext,
    user: User,
    request: Request,
    config: AiRuntimeConfig,
) -> AssistantSession:
    sharing = config.sharing
    if isinstance(context, InventoryContext):
        return build_inventory_session(
            user_id=user.id,
            context=context,
            reader=DbInventoryReader(user.id, user.username, context.source_id),
            sharing=sharing,
        )
    if isinstance(context, RunViewerContext):
        return build_run_viewer_session(
            user_id=user.id,
            context=context,
            reader=DbRunReader(user.id),
            sharing=sharing,
        )
    if isinstance(context, WorkflowCanvasContext):
        registry = getattr(request.app.state, "plugin_service", None)
        if registry is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "plugin_registry_unavailable",
                    "message": "Plugin registry unavailable",
                },
            )
        return build_workflow_editor_session(
            user_id=user.id,
            context=context,
            registry=registry,
            references=DbReferenceReader(user.id, user.username),
            validator=DbWorkflowValidator(user.id, registry),
        )
    return build_template_editor_session(
        user_id=user.id, context=context, reader=DbTemplateReader(user.id)
    )


def _sse(event: ChatEvent) -> str:
    return f"event: {event.event}\ndata: {json.dumps(event.data)}\n\n"


@router.get("/status", response_model=AiStatusResponse)
def get_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: AiSettingsService = Depends(get_ai_settings_service),
) -> AiStatusResponse:
    allowed = RBACService(db).has_permission(current_user.id, "ai_assistant", "use")
    return service.status(current_user.id, has_permission=allowed)


@router.get("/settings", response_model=UserAiSettingsResponse, dependencies=[_USE])
def get_settings(
    current_user: User = Depends(get_current_user),
    service: AiSettingsService = Depends(get_ai_settings_service),
) -> UserAiSettingsResponse:
    return service.get(current_user.id)


@router.patch("/settings", response_model=UserAiSettingsResponse, dependencies=[_USE])
def update_settings(
    body: UserAiSettingsUpdate,
    current_user: User = Depends(get_current_user),
    service: AiSettingsService = Depends(get_ai_settings_service),
) -> UserAiSettingsResponse:
    try:
        return service.update(current_user.id, body)
    except AiAssistantError as exc:
        _raise_http(exc)


@router.post("/settings/test", dependencies=[_USE, Depends(_TEST_BUDGET)])
async def test_settings(
    current_user: User = Depends(get_current_user),
    service: AiSettingsService = Depends(get_ai_settings_service),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        config = service.require_runtime_config(current_user.id, require_enabled=False)
    except AiAssistantError as exc:
        _raise_http(exc)
    finally:
        # Hand the pooled connection back before the (slow) provider call; get_db would
        # otherwise only release it after the response.
        db.close()
    return await check_connection(config)


@router.post("/chat", dependencies=[_USE, Depends(_CHAT_BUDGET)])
def chat(
    body: ChatRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: AiSettingsService = Depends(get_ai_settings_service),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    try:
        config: AiRuntimeConfig = service.require_runtime_config(current_user.id)
    except AiAssistantError as exc:
        _raise_http(exc)
    finally:
        # A StreamingResponse keeps get_db's session open until the stream ends (up to
        # minutes); release the pooled connection now. The stream never touches the DB.
        db.close()
    messages = [ChatMessage(role=m.role, content=m.content) for m in body.messages]
    system = BASE_SYSTEM_PROMPT
    toolbox: Toolbox | None = None
    if body.context is not None:
        session = _session_for(body.context, current_user, request, config)
        system, toolbox = session.system, session.toolbox

    async def event_stream() -> AsyncIterator[str]:
        async for event in stream_chat(config, messages, system=system, toolbox=toolbox):
            yield _sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
