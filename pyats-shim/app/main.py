"""pyATS HTTP shim -- FastAPI app exposing health checks and a job-execution endpoint."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.diff import router as diff_router
from app.health import router as health_router
from app.job_runner import JobRunner
from app.jobs import router as jobs_router
from app.parse import router as parse_router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.job_runner = JobRunner(settings)
    logger.info(
        "pyATS shim started (port=%s, max_concurrent_jobs=%s, job_timeout_seconds=%s)",
        settings.port,
        settings.max_concurrent_jobs,
        settings.job_timeout_seconds,
    )
    yield


app = FastAPI(title="pyATS Shim", lifespan=lifespan)
app.include_router(health_router)
app.include_router(jobs_router)
app.include_router(diff_router)
app.include_router(parse_router)
