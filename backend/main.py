from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from core.config import settings
from core.domain_exceptions import DomainError
from core.logging_config import configure_logging
from core.safe_http_errors import internal_error_detail
from core.version import __version__

# Fallback for direct uvicorn imports. start.py passes an explicit uvicorn log_config.
if not logging.root.handlers:
    configure_logging("app")

import service_factory
from core.database import SessionLocal, init_db, ping_database
from hatchet.worker_services import start_all
from models.health import ReadyResponse
from repositories.plugin_repository import PluginRepository
from routers.ai_assistant import router as ai_assistant_router
from routers.ai_conversations import router as ai_conversations_router
from routers.auth import router as auth_router
from routers.cache_settings import router as cache_settings_router
from routers.certificates import router as certificates_router
from routers.change_requests import router as change_requests_router
from routers.credentials import router as credentials_router
from routers.dashboard import router as dashboard_router
from routers.general_settings import router as general_settings_router
from routers.git import router as git_router
from routers.hatchet_settings import router as hatchet_settings_router
from routers.logging_settings import router as logging_settings_router
from routers.mail import router as mail_router
from routers.netmiko import router as netmiko_router
from routers.oidc import router as oidc_router
from routers.rbac import router as rbac_router
from routers.report_definitions import router as report_definitions_router
from routers.reports import router as reports_router
from routers.secret_manager import router as secret_manager_router
from routers.settings import router as settings_router
from routers.sources.agent import agent_source_crud_router, agent_source_ops_router
from routers.sources.batfish import (
    batfish_source_crud_router,
    batfish_source_discovery_router,
    batfish_source_ops_router,
    batfish_source_query_router,
)
from routers.sources.catalyst_center import (
    catalyst_center_source_crud_router,
    catalyst_center_source_ops_router,
)
from routers.sources.ise import ise_source_crud_router, ise_source_ops_router
from routers.sources.mattermost import (
    mattermost_source_crud_router,
    mattermost_source_ops_router,
)
from routers.sources.nautobot import (
    nautobot_source_crud_router,
    nautobot_source_ops_router,
)
from routers.sources.pyats import pyats_source_crud_router, pyats_source_ops_router
from routers.statistics import router as statistics_router
from routers.system import router as system_router
from routers.templates import router as templates_router
from routers.users import router as users_router
from routers.webhooks import router as webhooks_router
from routers.workflow_ai_session import router as workflow_ai_session_router
from routers.workflow_background_tier import router as workflow_background_tier_router
from routers.workflow_crypto_attribute import router as workflow_crypto_attribute_router
from routers.workflow_runs import router as workflow_runs_router
from routers.workflow_schedules import router as workflow_schedules_router
from routers.workflow_steps import router as workflow_steps_router
from routers.workflow_update_attribute import router as workflow_update_attribute_router
from routers.workflow_update_content import router as workflow_update_content_router
from routers.workflows import router as workflows_router
from services.auth.auth_service import AuthService
from services.auth.rbac_seed import ensure_ai_assistant_user, seed_rbac
from services.auth.rbac_service import RBACService
from services.health.probes import ping_redis
from services.health.ready import check_readiness
from services.logging.logging_settings_service import LoggingSettingsService
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from services.users.inventory_orphans import warn_about_orphaned_inventories

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()

    with SessionLocal() as db:
        admin_user = AuthService(db).ensure_initial_admin()
        seed_rbac(db)
        rbac = RBACService(db)
        # S10: only (re-)grant the bootstrap admin role when no *active* user
        # holds it (R2: a deactivated admin does not count).
        # First boot: the freshly created admin has no roles yet → granted.
        # A deliberate demotion of INITIAL_USERNAME survives a restart as long as
        # another active admin remains. If every active admin is gone, self-heal
        # by granting it back to INITIAL_USERNAME.
        if not rbac.role_has_members("admin"):
            if admin_user is None:
                logger.error(
                    "No user holds the 'admin' role and the initial user does not exist; "
                    "run backend/scripts/repair_database.py to recover access"
                )
            else:
                logger.warning(
                    "No user holds the 'admin' role; granting it to initial user '%s'",
                    admin_user.username,
                )
                rbac.assign_role_to_user_by_name(admin_user.id, "admin")

        ai_assistant_user = ensure_ai_assistant_user(db)
        rbac.assign_role_to_user_by_name(ai_assistant_user.id, "ai-assistant")

        LoggingSettingsService(db).apply_to_current_process("app")
        warn_about_orphaned_inventories(db)

    plugin_service = PluginRegistryService(
        PluginRepository(plugins_file=settings.plugins_file),
    )
    plugin_service.load_registry()
    app.state.plugin_service = plugin_service

    # The same start-up/shutdown block the Hatchet workers use; only the API may write to OpenBao.
    async with start_all("app", with_management=True, apply_logging=False):
        yield


app = FastAPI(
    title=settings.app_name,
    version=__version__,
    description="Backend API for Auxilium Manus.",
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    openapi_url="/openapi.json" if settings.docs_enabled else None,
    lifespan=lifespan,
)


DATABASE_UNAVAILABLE_MESSAGE = "The database is temporarily unavailable. Try again in a minute."
DATABASE_RETRY_AFTER_SECONDS = "30"


@app.exception_handler(OperationalError)
@app.exception_handler(PoolTimeoutError)
async def database_unavailable_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Database down, restarting, or the connection pool exhausted: a retryable 503 with an error id
    (O2-06). The driver message (host, role, SQL) stays in the log."""
    detail = internal_error_detail(message=DATABASE_UNAVAILABLE_MESSAGE)
    logger.error(
        "Database unavailable (error_id=%s): %s",
        detail["error_id"],
        type(exc).__name__,
        exc_info=exc,
        extra={"error_id": detail["error_id"]},
    )
    return JSONResponse(
        status_code=503,
        content={"detail": detail},
        headers={"Retry-After": DATABASE_RETRY_AFTER_SECONDS},
    )


@app.exception_handler(DomainError)
async def domain_error_handler(_request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.middleware("http")
async def limit_request_body(request: Request, call_next):
    """413 for a declared Content-Length above MAX_REQUEST_BODY_BYTES (S15).

    Chunked uploads without a Content-Length are not covered; enforce a limit in the
    reverse proxy as well (docker/DOCKER.md, "Request body size")."""
    limit = settings.max_request_body_bytes
    declared = request.headers.get("content-length")
    if limit and declared and declared.isdigit() and int(declared) > limit:
        return JSONResponse(status_code=413, content={"detail": "Request body too large"})
    return await call_next(request)


app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(ai_assistant_router, prefix=settings.api_prefix)
app.include_router(reports_router, prefix=settings.api_prefix)
app.include_router(report_definitions_router, prefix=settings.api_prefix)
app.include_router(mail_router, prefix=settings.api_prefix)
app.include_router(ai_conversations_router, prefix=settings.api_prefix)
app.include_router(oidc_router, prefix=settings.api_prefix)
app.include_router(git_router, prefix=settings.api_prefix)
app.include_router(nautobot_source_ops_router, prefix=settings.api_prefix)
app.include_router(nautobot_source_crud_router, prefix=settings.api_prefix)
app.include_router(ise_source_crud_router, prefix=settings.api_prefix)
app.include_router(ise_source_ops_router, prefix=settings.api_prefix)
app.include_router(catalyst_center_source_crud_router, prefix=settings.api_prefix)
app.include_router(catalyst_center_source_ops_router, prefix=settings.api_prefix)
app.include_router(pyats_source_crud_router, prefix=settings.api_prefix)
app.include_router(pyats_source_ops_router, prefix=settings.api_prefix)
app.include_router(agent_source_crud_router, prefix=settings.api_prefix)
app.include_router(agent_source_ops_router, prefix=settings.api_prefix)
app.include_router(batfish_source_crud_router, prefix=settings.api_prefix)
app.include_router(batfish_source_ops_router, prefix=settings.api_prefix)
app.include_router(batfish_source_query_router, prefix=settings.api_prefix)
app.include_router(batfish_source_discovery_router, prefix=settings.api_prefix)
app.include_router(mattermost_source_crud_router, prefix=settings.api_prefix)
app.include_router(mattermost_source_ops_router, prefix=settings.api_prefix)
app.include_router(workflow_steps_router, prefix=settings.api_prefix)
app.include_router(workflow_update_attribute_router, prefix=settings.api_prefix)
app.include_router(workflow_update_content_router, prefix=settings.api_prefix)
app.include_router(workflow_crypto_attribute_router, prefix=settings.api_prefix)
app.include_router(workflows_router, prefix=settings.api_prefix)
app.include_router(workflow_runs_router, prefix=settings.api_prefix)
app.include_router(workflow_schedules_router, prefix=settings.api_prefix)
app.include_router(change_requests_router, prefix=settings.api_prefix)
app.include_router(webhooks_router, prefix=settings.api_prefix)
app.include_router(workflow_background_tier_router, prefix=settings.api_prefix)
app.include_router(workflow_ai_session_router, prefix=settings.api_prefix)
app.include_router(dashboard_router, prefix=settings.api_prefix)
app.include_router(statistics_router, prefix=settings.api_prefix)
app.include_router(settings_router, prefix=settings.api_prefix)
app.include_router(credentials_router, prefix=settings.api_prefix)
app.include_router(secret_manager_router, prefix=settings.api_prefix)
app.include_router(templates_router, prefix=settings.api_prefix)
app.include_router(netmiko_router, prefix=settings.api_prefix)
app.include_router(hatchet_settings_router, prefix=settings.api_prefix)
app.include_router(cache_settings_router, prefix=settings.api_prefix)
app.include_router(logging_settings_router, prefix=settings.api_prefix)
app.include_router(general_settings_router, prefix=settings.api_prefix)
app.include_router(rbac_router, prefix=settings.api_prefix)
app.include_router(users_router, prefix=settings.api_prefix)
app.include_router(system_router, prefix=settings.api_prefix)
app.include_router(certificates_router, prefix=settings.api_prefix)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"], response_model=ReadyResponse)
async def health_ready(response: Response) -> ReadyResponse:
    def vault_status() -> bool | None:
        if not settings.vault_enabled:
            return None
        runtime = service_factory.get_vault_service()
        return bool(runtime is not None and runtime.healthy)

    status_code, body = await check_readiness(
        ping_database=ping_database,
        ping_redis=lambda: ping_redis(settings.redis_url),
        vault_status=vault_status,
    )
    response.status_code = status_code
    return body
