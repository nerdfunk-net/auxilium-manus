"""S6-08: the schema is served only when the docs are."""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.mark.parametrize("enabled", [False, True])
def test_openapi_follows_docs_flag(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    import main
    from core.config import settings

    monkeypatch.setattr(settings, "docs_enabled", enabled)
    module = importlib.reload(main)
    try:
        client = TestClient(module.app, raise_server_exceptions=False)
        expected = 200 if enabled else 404
        assert client.get("/openapi.json").status_code == expected
        assert client.get("/docs").status_code == expected
    finally:
        monkeypatch.undo()
        importlib.reload(main)
