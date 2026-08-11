"""Liveness (/health) and pyATS-functional (/health/pyats) checks.

Kept separate on purpose: /health only proves the FastAPI process is up (used
by the Docker healthcheck); /health/pyats additionally imports pyats/genie so
callers (the backend's test-connection flow) can distinguish "shim
unreachable" from "shim up but pyATS is broken inside the container".
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@router.get("/health/pyats")
async def health_pyats() -> dict:
    try:
        import genie
        import pyats
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller, not raised
        logger.exception("pyATS/Genie import failed")
        return {"status": "error", "detail": str(exc)}

    return {
        "status": "ok",
        "pyats_version": getattr(pyats, "__version__", "unknown"),
        "genie_version": getattr(genie, "__version__", "unknown"),
    }
