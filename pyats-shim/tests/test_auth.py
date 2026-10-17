import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.auth import require_bearer_token
from app.config import get_settings
from tests import TEST_TOKEN


@pytest.fixture(autouse=True)
def _shim_token(monkeypatch):
    monkeypatch.setenv("PYATS_SHIM_TOKEN", TEST_TOKEN)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    app = FastAPI()

    @app.get("/protected", dependencies=[Depends(require_bearer_token)])
    def protected():
        return {"ok": True}

    return TestClient(app)


def test_missing_authorization_header_rejected(client):
    response = client.get("/protected")
    assert response.status_code == 401


def test_wrong_token_rejected(client):
    response = client.get("/protected", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_correct_token_accepted(client):
    response = client.get(
        "/protected", headers={"Authorization": f"Bearer {TEST_TOKEN}"}
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_short_token_refuses_to_start(monkeypatch):
    monkeypatch.setenv("PYATS_SHIM_TOKEN", "too-short")
    get_settings.cache_clear()
    with pytest.raises(RuntimeError, match="at least 32"):
        get_settings()


def test_non_ascii_bearer_is_401_not_500(client):
    response = client.get(
        "/protected", headers={"Authorization": "Bearer pässword".encode("latin-1")}
    )
    assert response.status_code == 401
