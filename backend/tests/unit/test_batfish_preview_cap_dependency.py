"""The ad-hoc row endpoints set the preview row limit for the request (B3)."""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from models.batfish import MAX_PREVIEW_ROWS
from routers.sources.batfish.query import _cap_preview_rows
from services.batfish.client import PREVIEW_ROW_LIMIT


def test_endpoint_sees_the_limit_and_it_does_not_leak() -> None:
    app = FastAPI()

    @app.get("/async", dependencies=[Depends(_cap_preview_rows)])
    async def async_endpoint() -> dict:
        return {"limit": PREVIEW_ROW_LIMIT.get()}

    @app.get("/sync", dependencies=[Depends(_cap_preview_rows)])
    def sync_endpoint() -> dict:
        return {"limit": PREVIEW_ROW_LIMIT.get()}

    @app.get("/none")
    async def uncapped() -> dict:
        return {"limit": PREVIEW_ROW_LIMIT.get()}

    with TestClient(app) as client:
        assert client.get("/async").json() == {"limit": MAX_PREVIEW_ROWS}
        assert client.get("/sync").json() == {"limit": MAX_PREVIEW_ROWS}
        assert client.get("/none").json() == {"limit": None}
