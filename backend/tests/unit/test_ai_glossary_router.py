"""/ai/glossary: admin-only over HTTP, CRUD, strict bodies."""

from __future__ import annotations

import pytest
from _auth_helpers import make_user, token_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.auth import get_current_user, verify_token
from core.config import settings
from core.database import get_db
from core.domain_exceptions import DomainError
from core.models.ai_glossary import AiGlossaryName, AiGlossaryTerm
from core.models.base import Base
from core.models.users import User
from routers import ai_glossary
from services.auth.rbac_service import RBACService

BODY = {
    "term": "core",
    "aliases": ["backbone"],
    "source_id": "nb",
    "filter": {"conditions": [{"field": "role", "operator": "equals", "value": "Network"}]},
}


class _Reader:
    def __init__(self, *_a, **_k) -> None:
        pass

    async def field_values(self, field):
        return [{"value": "Network", "label": "Network"}] if field == "role" else []


@pytest.fixture
def admin(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    state = {"value": True}
    monkeypatch.setattr(RBACService, "has_role", lambda self, *_a, **_k: state["value"])
    monkeypatch.setattr(settings, "ai_assistant_enabled", True)
    monkeypatch.setattr(ai_glossary, "DbInventoryReader", _Reader)
    return state


@pytest.fixture
def client(admin: dict[str, bool]) -> TestClient:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(
        engine, tables=[User.__table__, AiGlossaryTerm.__table__, AiGlossaryName.__table__]
    )
    session = sessionmaker(bind=engine)()
    session.add(User(id=1, username="tester", email="t@x.y", password_hash="x"))
    session.commit()
    app = FastAPI()
    app.include_router(ai_glossary.router, prefix="/api")

    @app.exception_handler(DomainError)
    async def _domain(_request, exc: DomainError):
        from fastapi.responses import JSONResponse

        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: make_user(1)
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[ai_glossary._WRITE_BUDGET] = lambda: None
    # The role check reads the user through make_auth_db; the glossary uses the same session.
    return TestClient(app)


def test_non_admin_is_refused_everywhere(client: TestClient, admin: dict[str, bool]) -> None:
    admin["value"] = False

    assert client.get("/api/ai/glossary").status_code == 403
    assert client.post("/api/ai/glossary", json=BODY).status_code == 403
    assert client.put("/api/ai/glossary/1", json=BODY).status_code == 403
    assert client.delete("/api/ai/glossary/1").status_code == 403


def test_crud_round_trip(client: TestClient) -> None:
    created = client.post("/api/ai/glossary", json=BODY)
    assert created.status_code == 201, created.text
    term_id = created.json()["id"]

    listed = client.get("/api/ai/glossary", params={"q": "backb"}).json()
    assert listed["total"] == 1 and listed["items"][0]["term"] == "core"

    changed = {**BODY, "aliases": ["bb"]}
    assert client.put(f"/api/ai/glossary/{term_id}", json=changed).json()["aliases"] == ["bb"]
    assert client.delete(f"/api/ai/glossary/{term_id}").status_code == 204
    assert client.delete(f"/api/ai/glossary/{term_id}").status_code == 404


def test_duplicate_is_409_and_unknown_field_is_422(client: TestClient) -> None:
    client.post("/api/ai/glossary", json=BODY)

    assert client.post("/api/ai/glossary", json=BODY).status_code == 409
    assert client.post("/api/ai/glossary", json={**BODY, "extra": 1}).status_code == 422


def test_disabled_operator_switch_hides_the_api(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "ai_assistant_enabled", False)

    assert client.get("/api/ai/glossary").status_code == 404
