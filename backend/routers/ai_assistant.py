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
import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from core.auth import get_current_user, require_permission, require_role
from core.config import settings
from core.database import get_db
from core.domain_exceptions import DomainError
from core.models.users import User
from core.rate_limit import rate_limited
from core.safe_http_errors import raise_internal_server_error
from models.ai_assistant import (
    AiProxySettingsResponse,
    AiProxySettingsUpdate,
    AiStatusResponse,
    ChatRequest,
    CommandParseError,
    ConfigTextResponse,
    DeviceCommandConfirmRequest,
    DeviceCommandResponse,
    GeneralContext,
    InventoryContext,
    ParsedRowsResponse,
    ReportsContext,
    RunViewerContext,
    TemplateEditorContext,
    UserAiSettingsResponse,
    UserAiSettingsUpdate,
    WorkflowCanvasContext,
    WorkflowRunConfirmRequest,
    WorkflowRunConfirmResponse,
)
from services.ai_assistant.aci_reader import DbAciReader
from services.ai_assistant.agent_loop import DEFAULT_BUDGET
from services.ai_assistant.audit import AuditContext, log_config_download
from services.ai_assistant.batfish_reader import DbBatfishReader
from services.ai_assistant.catalyst_center_reader import DbCatalystCenterReader
from services.ai_assistant.chat_service import ChatEvent, check_connection, stream_chat
from services.ai_assistant.client_data_reader import DbClientDataReader
from services.ai_assistant.command_policy import CommandNotAllowedError
from services.ai_assistant.config_backup import DbConfigBackupReader
from services.ai_assistant.device_access import (
    DbDeviceCommandRunner,
    DbDeviceResolver,
    DeviceAccessDeniedError,
    DeviceAccessError,
    DeviceAmbiguousError,
    DeviceNoAddressError,
    DeviceNotFoundError,
    DeviceUnsupportedPlatformError,
)
from services.ai_assistant.device_exec_service import (
    DeviceChangedError,
    DeviceCommandExecutor,
    InvalidConfirmationError,
    SecretsUnavailableError,
    TooManyRunsError,
)
from services.ai_assistant.dns_resolver import SystemDnsResolver
from services.ai_assistant.exceptions import (
    AiAssistantDisabledError,
    AiAssistantError,
    AiAssistantNotConfiguredError,
    AiSettingsValidationError,
)
from services.ai_assistant.genie_parser import DbGenieParser, has_pyats_source
from services.ai_assistant.glossary_reader import DbGlossaryReader
from services.ai_assistant.inventory_reader import DbInventoryReader
from services.ai_assistant.known_secrets import try_load_visible_secret_values
from services.ai_assistant.nautobot_query_reader import DbNautobotQueryReader
from services.ai_assistant.parse_service import PARSED_KIND
from services.ai_assistant.prompts import BASE_SYSTEM_PROMPT
from services.ai_assistant.providers.base import ChatMessage
from services.ai_assistant.proxy_settings_service import AiProxySettingsService
from services.ai_assistant.redaction import RedactionBudgetExceeded
from services.ai_assistant.released_run_builder import ReleasedRunError
from services.ai_assistant.released_workflow_reader import (
    DbReleasedWorkflowReader,
    ReleasedWorkflowAccessError,
)
from services.ai_assistant.report_reader import DbReportReader
from services.ai_assistant.results.factory import get_result_store
from services.ai_assistant.results.store import (
    ResultStore,
    ResultStoreUnavailableError,
    StoredResult,
)
from services.ai_assistant.run_reader import DbRunReader
from services.ai_assistant.settings_service import AiRuntimeConfig, AiSettingsService
from services.ai_assistant.surfaces import (
    AssistantSession,
    build_general_session,
    build_inventory_session,
    build_reports_session,
    build_run_viewer_session,
    build_template_editor_session,
    build_workflow_editor_session,
)
from services.ai_assistant.template_reader import DbTemplateReader
from services.ai_assistant.token_once import ConfirmationStoreUnavailableError
from services.ai_assistant.tools.base import Toolbox
from services.ai_assistant.tools.config_backup_tools import HANDLE_KIND as CONFIG_BACKUP_KIND
from services.ai_assistant.workflow_reader import DbReferenceReader, DbWorkflowValidator
from services.ai_assistant.workflow_run_exec import WorkflowRunExecutor
from services.ai_assistant.workflow_run_token import InvalidRunTokenError
from services.auth.rbac_service import RBACService
from services.settings.settings_service import SettingsService

logger = logging.getLogger(__name__)

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
    | ReportsContext
    | GeneralContext,
    user: User,
    request: Request,
    config: AiRuntimeConfig,
    *,
    can_write_workflows: bool = False,
    can_save_inventories: bool = False,
    can_query_batfish: bool = False,
    can_run_device_commands: bool = False,
    can_read_config_backups: bool = False,
    can_read_nautobot: bool = False,
    can_read_catalyst: bool = False,
    can_read_aci: bool = False,
    can_read_client_data: bool = False,
    can_read_runs: bool = False,
    can_start_released: bool = False,
) -> AssistantSession:
    sharing = config.sharing
    # S5-04: with run / device content shared, scrub the exact secrets the user can resolve.
    known: list[str] | tuple[()] = ()
    if sharing.content:
        loaded = try_load_visible_secret_values(user.id)
        if loaded is None:
            # Fail closed: without the exact credential values only pattern redaction would
            # protect the content, so it is not shared for this request.
            sharing = replace(sharing, content=False)
        else:
            known = loaded
    if isinstance(context, GeneralContext):
        return build_general_session(
            user_id=user.id,
            reader=DbBatfishReader(user.id),
            store=get_result_store(),
            sharing=sharing,
            may_query_batfish=can_query_batfish,
            known_secrets=known,
            # The output of a device command is content: without the opt-in (or when the exact
            # secret values could not be loaded, which switches content off above) the tool would
            # be useless, so it is not offered.
            device_resolver=(
                DbDeviceResolver(user.id) if can_run_device_commands and sharing.content else None
            ),
            # Genie (doc/AI_TOOL_CHAIN.md §43) only when the user may read exactly one pyATS source.
            genie_parser=(
                DbGenieParser(user.id)
                if can_run_device_commands and sharing.content and has_pyats_source(user.id)
                else None
            ),
            # Backed-up configs are content too, and need the repository file read permission.
            config_reader=(
                DbConfigBackupReader(user.id, DbDeviceResolver(user.id))
                if can_read_config_backups and sharing.content
                else None
            ),
            # Documented inventory (DCIM / IPAM); what it may show is gated per field by the
            # sharing policy inside the tools.
            nautobot_reader=DbNautobotQueryReader(user.id) if can_read_nautobot else None,
            # Catalyst Center: offered with the permission alone, so a missing source is reported
            # to the user by the tool instead of the tools silently vanishing.
            catalyst_reader=DbCatalystCenterReader(user.id) if can_read_catalyst else None,
            # ACI: offered with the permission alone, like Catalyst Center.
            aci_reader=DbAciReader(user.id) if can_read_aci else None,
            # Client data: offered with the permission alone; the reader checks it per call.
            client_data_reader=DbClientDataReader(user.id) if can_read_client_data else None,
            # DNS: the operator switch alone; the tool checks the data switches and the suffix
            # policy (doc/AI_TOOL_CHAIN.md §50).
            dns_resolver=(
                SystemDnsResolver(settings.ai_dns_allowed_suffixes)
                if settings.ai_dns_lookup_enabled
                else None
            ),
            # Run explanations reuse the runs-page reader; it checks workflow_runs:read per call.
            run_reader=DbRunReader(user.id) if can_read_runs else None,
            # Released workflows: the reader checks workflows:execute and visibility per call.
            released_reader=DbReleasedWorkflowReader(user.id) if can_start_released else None,
        )
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
            may_propose=can_save_inventories,
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
            glossary=DbGlossaryReader("workflow_step"),
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
    can_save_inventories = False
    can_query_batfish = False
    can_run_device_commands = False
    can_read_config_backups = False
    can_read_nautobot = False
    can_read_catalyst = False
    can_read_aci = False
    can_read_client_data = False
    can_read_runs = False
    can_start_released = False
    try:
        config: AiRuntimeConfig = service.require_runtime_config(current_user.id)
        if isinstance(body.context, InventoryContext):
            # An inventory proposal is only useful to someone who can save it.
            can_save_inventories = RBACService(db).has_permission(
                current_user.id, "sources.nautobot", "write"
            )
        if isinstance(body.context, GeneralContext):
            # The Batfish tools show the same data as the query endpoints, so they need the same
            # permission; the reader checks it again on every call.
            rbac = RBACService(db)
            can_query_batfish = rbac.has_permission(current_user.id, "sources.batfish", "query")
            # Device commands: the operator switch, and the permission of the Netmiko preview API.
            can_run_device_commands = settings.ai_device_commands_enabled and rbac.has_permission(
                current_user.id, "netmiko", "execute"
            )
            can_read_config_backups = rbac.has_permission(current_user.id, "git.files", "read")
            # The Nautobot tools need the source permission and a configured source.
            can_read_nautobot = rbac.has_permission(
                current_user.id, "sources.nautobot", "read"
            ) and bool(SettingsService(db).list_nautobot_source_summaries().sources)
            can_read_catalyst = rbac.has_permission(
                current_user.id, "sources.catalyst_center", "read"
            )
            can_read_aci = rbac.has_permission(current_user.id, "sources.aci", "read")
            can_read_client_data = rbac.has_permission(current_user.id, "client_data", "read")
            can_read_runs = rbac.has_permission(current_user.id, "workflow_runs", "read")
            can_start_released = rbac.has_permission(current_user.id, "workflows", "execute")
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
    budget = DEFAULT_BUDGET
    if body.context is not None:
        try:
            session = _session_for(
                body.context,
                current_user,
                request,
                config,
                can_write_workflows=can_write_workflows,
                can_save_inventories=can_save_inventories,
                can_query_batfish=can_query_batfish,
                can_run_device_commands=can_run_device_commands,
                can_read_config_backups=can_read_config_backups,
                can_read_nautobot=can_read_nautobot,
                can_read_catalyst=can_read_catalyst,
                can_read_aci=can_read_aci,
                can_read_client_data=can_read_client_data,
                can_read_runs=can_read_runs,
                can_start_released=can_start_released,
            )
        except RedactionBudgetExceeded as exc:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail={"code": "ai_context_too_large", "message": str(exc)},
            ) from exc
        system, toolbox, budget = session.system, session.toolbox, session.budget
        # The user's own token cap replaces the surface default, only where a surface has one
        # (the editors have none and keep it).
        if config.max_turn_tokens is not None and budget.max_total_tokens is not None:
            budget = replace(budget, max_total_tokens=config.max_turn_tokens)

    audit = AuditContext(
        user_id=current_user.id,
        surface=body.context.surface if body.context is not None else "plain",
        provider=config.provider,
        model=config.model,
    )

    async def event_stream() -> AsyncIterator[str]:
        async for event in stream_chat(
            config, messages, system=system, toolbox=toolbox, audit=audit, budget=budget
        ):
            yield _sse(event)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# -- confirmed device commands (doc/AI_TOOL_CHAIN.md §29) -------------------------------------


def require_device_commands_enabled() -> None:
    """The operator switch ``AI_DEVICE_COMMANDS_ENABLED``: off means the route does not exist."""
    if not settings.ai_device_commands_enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


# Each confirmed run opens an SSH session; the budget matches the Netmiko preview API.
_DEVICE_BUDGET = rate_limited("ai-device-command", attempts=10, window_seconds=60)

_DEVICE_ERRORS: tuple[tuple[type[Exception], int, str, str], ...] = (
    (
        InvalidConfirmationError,
        status.HTTP_400_BAD_REQUEST,
        "invalid_confirmation",
        "This confirmation expired or is not valid. Ask the assistant again.",
    ),
    (
        DeviceChangedError,
        status.HTTP_409_CONFLICT,
        "device_changed",
        "The device name no longer points at the device that was shown. Ask again.",
    ),
    (
        TooManyRunsError,
        status.HTTP_429_TOO_MANY_REQUESTS,
        "too_many_runs",
        "You already have device commands running. Wait for them to finish.",
    ),
    (
        SecretsUnavailableError,
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "secrets_unavailable",
        "The output cannot be scrubbed safely right now, so nothing was run. Try again later.",
    ),
)
_DEVICE_ACCESS_ERRORS: tuple[tuple[type[DeviceAccessError], int, str], ...] = (
    (DeviceAccessDeniedError, status.HTTP_403_FORBIDDEN, "device_access_denied"),
    (DeviceNotFoundError, status.HTTP_404_NOT_FOUND, "device_not_found"),
    (DeviceAmbiguousError, status.HTTP_409_CONFLICT, "device_ambiguous"),
    (DeviceNoAddressError, status.HTTP_409_CONFLICT, "device_no_address"),
    (DeviceUnsupportedPlatformError, status.HTTP_409_CONFLICT, "device_platform_unsupported"),
)


def get_device_executor(current_user: User = Depends(get_current_user)) -> DeviceCommandExecutor:
    return DeviceCommandExecutor(
        DbDeviceResolver(current_user.id), DbDeviceCommandRunner(), get_result_store()
    )


def _device_http_error(exc: Exception) -> HTTPException | None:
    for kind, code_status, code, message in _DEVICE_ERRORS:
        if isinstance(exc, kind):
            return HTTPException(status_code=code_status, detail={"code": code, "message": message})
    for access_kind, code_status, code in _DEVICE_ACCESS_ERRORS:
        if isinstance(exc, access_kind):
            return HTTPException(
                status_code=code_status, detail={"code": code, "message": str(exc)}
            )
    if isinstance(exc, CommandNotAllowedError):
        return HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "command_not_allowed", "message": str(exc)},
        )
    return None


_RESULT_ROWS_BUDGET = rate_limited("ai-result-rows", attempts=30, window_seconds=60)


async def _own_content_result(
    handle: str, user: User, store: ResultStore, service: AiSettingsService
) -> StoredResult | None:
    """The caller's own stored result, or ``None`` (unknown, expired, malformed or not theirs).

    The content opt-in is checked on every call, like the assistant's own reads, so switching
    sharing off stops a download too. The caller still checks the kind of the result.
    """
    try:
        config = await asyncio.to_thread(service.require_runtime_config, user.id)
    except AiAssistantError as exc:
        _raise_http(exc)
    if not config.sharing.content:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "content_sharing_off",
                "message": "Sharing run and device content with the assistant is switched off.",
            },
        )
    try:
        return await store.get(user.id, handle)
    except ResultStoreUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "result_store_unavailable",
                "message": "Stored results are unavailable",
            },
        ) from exc


def _result_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "result_not_found", "message": "Unknown or expired result"},
    )


@router.get(
    "/results/{handle}/rows",
    response_model=ParsedRowsResponse,
    dependencies=[_OPERATOR, _USE, Depends(_RESULT_ROWS_BUDGET)],
)
async def get_parsed_rows(
    handle: str,
    response: Response,
    current_user: User = Depends(get_current_user),
    store: ResultStore = Depends(get_result_store),
    service: AiSettingsService = Depends(get_ai_settings_service),
) -> ParsedRowsResponse:
    """The full rows of a parsed device output, for a download (doc/AI_TOOL_CHAIN.md §43).

    Only the caller's own ``parsed_output`` handles resolve (a raw output, another user's handle
    and an expired one are all the same 404).
    """
    stored = await _own_content_result(handle, current_user, store, service)
    if stored is None or stored.kind != PARSED_KIND or stored.rows is None:
        raise _result_not_found()
    response.headers["Cache-Control"] = "no-store"
    meta = stored.meta or {}
    return ParsedRowsResponse(parser=str(meta.get("parser", "")), rows=stored.rows)


@router.get(
    "/results/{handle}/text",
    response_model=ConfigTextResponse,
    dependencies=[_OPERATOR, _USE, Depends(_RESULT_ROWS_BUDGET)],
)
async def get_config_text(
    handle: str,
    response: Response,
    current_user: User = Depends(get_current_user),
    store: ResultStore = Depends(get_result_store),
    service: AiSettingsService = Depends(get_ai_settings_service),
    db: Session = Depends(get_db),
) -> ConfigTextResponse:
    """The redacted text of a backed-up config, for a download (doc/AI_TOOL_CHAIN.md §30).

    Only the caller's own ``config_backup`` handles resolve; anything else is the same 404. The
    right to read config files is checked again (as ``get_config_backup`` does), so revoking it
    stops a handle that is still alive, and every download is logged (ids, never content).
    """
    stored = await _own_content_result(handle, current_user, store, service)
    if stored is None or stored.kind != CONFIG_BACKUP_KIND or stored.text is None:
        raise _result_not_found()
    if not await asyncio.to_thread(
        RBACService(db).has_permission, current_user.id, "git.files", "read"
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "config_access_denied",
                "message": "You no longer have access to configuration backups.",
            },
        )
    # The redacted configuration must not sit in the browser's HTTP cache.
    response.headers["Cache-Control"] = "no-store"
    meta = stored.meta or {}
    log_config_download(user_id=current_user.id, device=str(meta.get("device", "")), handle=handle)
    committed_at = meta.get("committed_at")
    return ConfigTextResponse(
        device=str(meta.get("device", "")),
        kind=str(meta.get("kind", "")),
        committed_at=committed_at if isinstance(committed_at, str) else None,
        text=stored.text,
    )


@router.post(
    "/exec/device-command",
    response_model=DeviceCommandResponse,
    dependencies=[
        _OPERATOR,
        Depends(require_device_commands_enabled),
        _USE,
        Depends(require_permission("netmiko", "execute")),
        Depends(_DEVICE_BUDGET),
    ],
)
async def confirm_device_command(
    body: DeviceCommandConfirmRequest,
    current_user: User = Depends(get_current_user),
    executor: DeviceCommandExecutor = Depends(get_device_executor),
    service: AiSettingsService = Depends(get_ai_settings_service),
) -> DeviceCommandResponse:
    """The user clicked Run on a proposed device command.

    The device and commands come from the signed token, the SSH credential from the body (and is
    checked against the user's own credentials). Everything is verified again here.
    """
    # The card is offered only with the content opt-in, and a token lives for ten minutes: turning
    # sharing off in between must stop the run (no SSH session, nothing stored), not only the offer.
    try:
        config = await asyncio.to_thread(service.require_runtime_config, current_user.id)
    except AiAssistantError as exc:
        _raise_http(exc)
    if not config.sharing.content:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "content_sharing_off",
                "message": "Sharing run and device content with the assistant is switched off.",
            },
        )
    try:
        result = await executor.execute(
            user_id=current_user.id,
            token=body.token,
            credential_id=body.credential_id,
            network_driver=body.network_driver,
        )
    except DomainError:
        raise
    except Exception as exc:
        mapped = _device_http_error(exc)
        if mapped is not None:
            raise mapped from exc
        raise_internal_server_error(logger, "Failed to run the device command", exc)
    return DeviceCommandResponse(
        success=result.success,
        error=result.error,
        device_name=result.device_name,
        commands=list(result.commands),
        output=result.output,
        truncated=result.truncated,
        handle=result.handle,
        parser=result.parser,
        parsed_handle=result.parsed_handle,
        parsed_text=result.parsed_text,
        parse_errors=[
            CommandParseError(command=command, error=error)
            for command, error in result.parse_errors
        ],
    )


# -- confirmed workflow runs (doc/AI_TOOL_CHAIN.md §16) ----------------------------------------

# Each confirmed start creates a run; the budget bounds a loop of proposals and clicks.
_WORKFLOW_START_BUDGET = rate_limited("ai-workflow-start", attempts=10, window_seconds=60)


def get_workflow_run_executor(
    current_user: User = Depends(get_current_user),
) -> WorkflowRunExecutor:
    return WorkflowRunExecutor(DbReleasedWorkflowReader(current_user.id))


@router.post(
    "/exec/workflow-run",
    response_model=WorkflowRunConfirmResponse,
    dependencies=[
        _OPERATOR,
        _USE,
        Depends(require_permission("workflows", "execute")),
        Depends(_WORKFLOW_START_BUDGET),
    ],
)
async def confirm_workflow_run(
    body: WorkflowRunConfirmRequest,
    current_user: User = Depends(get_current_user),
    executor: WorkflowRunExecutor = Depends(get_workflow_run_executor),
) -> WorkflowRunConfirmResponse:
    """The user clicked Run on a proposed workflow run.

    Workflow, inputs and devices come from the signed token. The run starts as the user, and only
    while the workflow is still released.
    """
    try:
        started = await executor.execute(
            user_id=current_user.id,
            token=body.token,
            credentials=body.credentials,
            free_ip_driver=body.free_ip_driver,
        )
    except InvalidRunTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "invalid_confirmation",
                "message": "This confirmation expired or is not valid. Ask the assistant again.",
            },
        ) from exc
    except ReleasedWorkflowAccessError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "workflow_not_released", "message": str(exc)},
        ) from exc
    except ConfirmationStoreUnavailableError as exc:
        # Fail closed: a start that cannot be recorded as used is not started.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "confirmation_unavailable",
                "message": "The workflow could not be confirmed right now. Try again shortly.",
            },
        ) from exc
    except ReleasedRunError as exc:
        # The message is written by us (no exception text from a deeper layer).
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "invalid_workflow_start", "message": str(exc)},
        ) from exc
    except DomainError:
        raise
    except Exception as exc:
        raise_internal_server_error(logger, "Failed to start the workflow run", exc)
    return WorkflowRunConfirmResponse(run_id=started.run_id, workflow_id=started.workflow_id)
