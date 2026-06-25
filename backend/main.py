from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.config import settings

# Fallback for direct uvicorn imports. start.py passes an explicit uvicorn log_config.
if not logging.root.handlers:
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format=settings.log_format,
        stream=sys.stdout,
    )

import service_factory
from core.database import SessionLocal, init_db
from repositories.plugin_repository import PluginRepository
from routers.auth import router as auth_router
from routers.credentials import router as credentials_router
from routers.cache_settings import router as cache_settings_router
from routers.hatchet_settings import router as hatchet_settings_router
from routers.nautobot.custom_fields import router as nautobot_custom_fields_router
from routers.settings import router as settings_router
from routers.git import router as git_router
from routers.sources.git.ops import router as git_source_ops_router
from routers.sources.nautobot import (
    nautobot_source_crud_router,
    nautobot_source_ops_router,
)
from routers.workflow_jinja_template import router as workflow_jinja_template_router
from routers.workflow_runs import router as workflow_runs_router
from routers.workflow_steps import router as workflow_steps_router
from routers.workflows import router as workflows_router
from services.auth.auth_service import AuthService
from services.nautobot.client import NautobotService
from services.plugin_registry.plugin_registry_service import PluginRegistryService


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()

    with SessionLocal() as db:
        AuthService(db).ensure_initial_admin()

    plugin_service = PluginRegistryService(
        PluginRepository(plugins_file=settings.plugins_file),
    )
    plugin_service.load_registry()
    app.state.plugin_service = plugin_service

    nautobot_service = NautobotService()
    await nautobot_service.startup()
    service_factory.set_nautobot_app_service(nautobot_service)
    service_factory.build_cache_service()

    yield

    await nautobot_service.shutdown()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Backend API for Auxilium Manus.",
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    lifespan=lifespan,
)

app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(git_router, prefix=settings.api_prefix)
app.include_router(git_source_ops_router, prefix=settings.api_prefix)
app.include_router(nautobot_source_ops_router, prefix=settings.api_prefix)
app.include_router(nautobot_source_crud_router, prefix=settings.api_prefix)
app.include_router(nautobot_custom_fields_router, prefix=settings.api_prefix)
app.include_router(workflow_steps_router, prefix=settings.api_prefix)
app.include_router(workflow_jinja_template_router, prefix=settings.api_prefix)
app.include_router(workflows_router, prefix=settings.api_prefix)
app.include_router(workflow_runs_router, prefix=settings.api_prefix)
app.include_router(settings_router, prefix=settings.api_prefix)
app.include_router(credentials_router, prefix=settings.api_prefix)
app.include_router(hatchet_settings_router, prefix=settings.api_prefix)
app.include_router(cache_settings_router, prefix=settings.api_prefix)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
