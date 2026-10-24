"""In-app AI assistant API (doc/ai_integration/AI_ASSISTANT.md).

``GET /ai/status`` is open to any signed-in user so the UI can decide whether to render
assistant surfaces. Everything else requires ``ai_assistant:use``. The enable switch is
enforced here on the server for chat; hiding the UI is only a convenience. The one deliberate
exception is ``POST /ai/settings/test``, which works while the assistant is off so a user can
verify a key before switching it on (it is still permission-gated and rate limited).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission, require_role
from core.config import settings
from core.database import get_db
from core.models.users import User
from core.rate_limit import rate_limited
from models.ai_assistant import (
    AiProxySettingsResponse,
    AiProxySettingsUpdate,
    AiStatusResponse,
    ChatRequest,
    InventoryContext,
    ReportsContext,
    RunViewerContext,
    TemplateEditorContext,
    UserAiSettingsResponse,
    UserAiSettingsUpdate,
    WorkflowCanvasContext,
)
from services.ai_assistant.audit import AuditContext
from services.ai_assistant.chat_service import ChatEvent, check_connection, stream_chat
from services.ai_assistant.exceptions import (
    AiAssistantDisabledError,
    AiAssistantError,
    AiAssistantNotConfiguredError,
    AiSettingsValidationError,
)
from services.ai_assistant.inventory_reader import DbInventoryReader
from services.ai_assistant.known_secrets import load_visible_secret_values
from services.ai_assistant.prompts import BASE_SYSTEM_PROMPT
from services.ai_assistant.providers.base import ChatMessage
from services.ai_assistant.proxy_settings_service import AiProxySettingsService
from services.ai_assistant.redaction import RedactionBudgetExceeded
from services.ai_assistant.report_reader import DbReportReader
from services.ai_assistant.run_reader import DbRunReader
from services.ai_assistant.settings_service import AiRuntimeConfig, AiSettingsService
from services.ai_assistant.surfaces import (
    AssistantSession,
    build_inventory_session,
    build_reports_session,
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


def require_operator_enabled() -> None:
    """The operator switch (``AI_ASSISTANT_ENABLED``): while it is off the assistant routes
    do not exist (404). ``/ai/status`` stays up and reports ``operator_disabled`` so the UI can
    explain why."""
    if not settings.ai_assistant_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


_OPERATOR = Depends(require_operator_enabled)

# Chat is the expensive path (an outbound LLM call per request); the test is a cheap probe
# but still spends the user's own quota, so it gets a much smaller budget.
_CHAT_BUDGET = rate_limited("ai-chat", attempts=30, window_seconds=60)
_TEST_BUDGET = rate_limited("ai-test", attempts=6, window_seconds=60)
# Saving resolves the custom server URL's DNS name, so it is bounded too.
_SETTINGS_BUDGET = rate_limited("ai-settings", attempts=20, window_seconds=60)

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
    context: TemplateEditorContext
    | WorkflowCanvasContext
    | RunViewerContext
    | InventoryContext
    | ReportsContext,
    user: User,
    request: Request,
    config: AiRuntimeConfig,
    *,
    can_write_workflows: bool = False,
) -> AssistantSession:
    sharing = config.sharing
    # S5-04: with run / device content shared, scrub the exact secrets the user can resolve.
    known = load_visible_secret_values(user.id) if sharing.content else ()
    if isinstance(context, ReportsContext):
        return build_reports_session(
            user_id=user.id,
            context=context,
            reader=DbReportReader(user.id, context.source_id),
            sharing=sharing,
        )
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
            known_secrets=known,
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
            may_propose=can_write_workflows,
        )
    return build_template_editor_session(
        user_id=user.id,
        context=context,
        reader=DbTemplateReader(user.id),
        known_secrets=known,
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


@router.get("/settings", response_model=UserAiSettingsResponse, dependencies=[_OPERATOR, _USE])
def get_settings(
    current_user: User = Depends(get_current_user),
    service: AiSettingsService = Depends(get_ai_settings_service),
) -> UserAiSettingsResponse:
    return service.get(current_user.id)


@router.patch(
    "/settings",
    response_model=UserAiSettingsResponse,
    dependencies=[_OPERATOR, _USE, Depends(_SETTINGS_BUDGET)],
)
def update_settings(
    body: UserAiSettingsUpdate,
    current_user: User = Depends(get_current_user),
    service: AiSettingsService = Depends(get_ai_settings_service),
    db: Session = Depends(get_db),
) -> UserAiSettingsResponse:
    # A custom endpoint makes the backend send requests to an address the user chose, inside the
    # internal network. Like the other outbound source settings (auth.md P3) that is admin-only.
    if body.base_url and not RBACService(db).has_role(current_user.id, "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "ai_base_url_admin_only",
                "message": "Only an administrator can set a custom server URL",
            },
        )
    try:
        return service.update(current_user.id, body)
    except AiAssistantError as exc:
        _raise_http(exc)


# The proxy decides where every user's prompts and API keys travel, so it is admin-only (auth.md P3)
# and global. It is exercised by ``POST /ai/settings/test``, which now goes through it.
_ADMIN = Depends(require_role("admin"))


@router.get("/proxy", response_model=AiProxySettingsResponse, dependencies=[_OPERATOR, _ADMIN])
def get_proxy_settings(db: Session = Depends(get_db)) -> AiProxySettingsResponse:
    return AiProxySettingsService(db).get()


@router.put(
    "/proxy",
    response_model=AiProxySettingsResponse,
    dependencies=[_OPERATOR, _ADMIN, Depends(_SETTINGS_BUDGET)],
)
def update_proxy_settings(
    body: AiProxySettingsUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> AiProxySettingsResponse:
    try:
        return AiProxySettingsService(db).update(body, actor_user_id=current_user.id)
    except AiAssistantError as exc:
        _raise_http(exc)


@router.post("/settings/test", dependencies=[_OPERATOR, _USE, Depends(_TEST_BUDGET)])
async def test_settings(
    current_user: User = Depends(get_current_user),
    service: AiSettingsService = Depends(get_ai_settings_service),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        # Blocking DB read + key decryption: keep it off the event loop.
        config = await asyncio.to_thread(
            service.require_runtime_config, current_user.id, require_enabled=False
        )
    except AiAssistantError as exc:
        _raise_http(exc)
    finally:
        # Hand the pooled connection back before the (slow) provider call; get_db would
        # otherwise only release it after the response.
        db.close()
    return await check_connection(config)


@router.post("/chat", dependencies=[_OPERATOR, _USE, Depends(_CHAT_BUDGET)])
def chat(
    body: ChatRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    service: AiSettingsService = Depends(get_ai_settings_service),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    can_write_workflows = False
    try:
        config: AiRuntimeConfig = service.require_runtime_config(current_user.id)
        if isinstance(body.context, WorkflowCanvasContext):
            # S5-08: the editor tools list real credentials / sources / inventories, so they
            # need the same permission the workflow list does; proposing needs write.
            rbac = RBACService(db)
            if not rbac.has_permission(current_user.id, "workflows", "read"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail={
                        "code": "workflows_read_required",
                        "message": "The workflow assistant requires workflows:read",
                    },
                )
            can_write_workflows = rbac.has_permission(current_user.id, "workflows", "write")
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
        try:
            session = _session_for(
                body.context,
                current_user,
                request,
                config,
                can_write_workflows=can_write_workflows,
            )
        except RedactionBudgetExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={"code": "ai_context_too_large", "message": str(exc)},
            ) from exc
        system, toolbox = session.system, session.toolbox

    audit = AuditContext(
        user_id=current_user.id,
        surface=body.context.surface if body.context is not None else "plain",
        provider=config.provider,
        model=config.model,
    )

    async def event_stream() -> AsyncIterator[str]:
        async for event in stream_chat(
            config, messages, system=system, toolbox=toolbox, audit=audit
        ):
            yield _sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
