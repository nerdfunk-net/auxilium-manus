from fastapi.testclient import TestClient

from app.config import get_settings
from tests import TEST_TOKEN


def test_docs_are_not_served(monkeypatch):
    monkeypatch.setenv("PYATS_SHIM_TOKEN", TEST_TOKEN)
    get_settings.cache_clear()
    from app.main import app

    client = TestClient(app)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
