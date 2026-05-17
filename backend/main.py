from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from core.config import settings
from core.database import SessionLocal, init_db
from repositories.plugin_repository import PluginRepository
from routers.auth import router as auth_router
from routers.plugins import router as plugins_router
from services.auth_service import AuthService
from services.plugin_registry_service import PluginRegistryService


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

    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Backend API for Auxilium Manus.",
    docs_url="/docs" if settings.docs_enabled else None,
    redoc_url="/redoc" if settings.docs_enabled else None,
    lifespan=lifespan,
)

app.include_router(auth_router, prefix=settings.api_prefix)
app.include_router(plugins_router, prefix=settings.api_prefix)


@app.get("/health", tags=["health"])
async def health_check() -> dict[str, str]:
    return {"status": "ok"}
