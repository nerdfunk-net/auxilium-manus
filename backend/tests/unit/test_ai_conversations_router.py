"""/ai/conversations: permission gate, owner isolation over HTTP, status codes."""

from __future__ import annotations

import pytest
from _auth_helpers import make_auth_db, make_user, token_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.ai_conversations import AiConversation
from core.models.base import Base
from core.models.users import User
from routers.ai_conversations import get_conversation_service, router
from services.ai_assistant.conversation_service import AiConversationService
from services.auth.rbac_service import RBACService

BODY = {
    "surface": "template_editor",
    "subject_key": "7",
    "messages": [
        {"role": "user", "content": "make it shorter"},
        {
            "role": "assistant",
            "content": "ok",
            "tools": [{"id": "t1", "name": "get_template", "status": "done"}],
            "proposal": {"kind": "template", "summary": "shorter"},
        },
    ],
}


@pytest.fixture
def allowed(monkeypatch: pytest.MonkeyPatch) -> dict[str, bool]:
    state = {"value": True}
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: state["value"])
    return state


@pytest.fixture
def current() -> dict[str, User]:
    return {"user": make_user(1)}


@pytest.fixture
def client(allowed: dict[str, bool], current: dict[str, User]) -> TestClient:
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[User.__table__, AiConversation.__table__])
    session = sessionmaker(bind=engine)()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: current["user"]
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    app.dependency_overrides[get_conversation_service] = lambda: AiConversationService.from_session(
        session
    )
    return TestClient(app)


def test_create_list_get_update_delete(client: TestClient) -> None:
    created = client.post("/api/ai/conversations", json=BODY)
    assert created.status_code == 201, created.text
    conversation_id = created.json()["id"]
    assert created.json()["title"] == "make it shorter"

    listed = client.get(
        "/api/ai/conversations", params={"surface": "template_editor", "subject_key": "7"}
    )
    assert [c["id"] for c in listed.json()] == [conversation_id]
    assert listed.json()[0]["message_count"] == 2
    assert "messages" not in listed.json()[0]

    detail = client.get(f"/api/ai/conversations/{conversation_id}").json()
    assert detail["messages"][1]["proposal"] == {"kind": "template", "summary": "shorter"}

    renamed = client.put(f"/api/ai/conversations/{conversation_id}", json={"title": "Shorter"})
    assert renamed.status_code == 200 and renamed.json()["title"] == "Shorter"

    assert client.delete(f"/api/ai/conversations/{conversation_id}").status_code == 204
    assert client.get(f"/api/ai/conversations/{conversation_id}").status_code == 404


def test_other_user_gets_404(client: TestClient, current: dict[str, User]) -> None:
    conversation_id = client.post("/api/ai/conversations", json=BODY).json()["id"]

    current["user"] = make_user(2, username="other")
    assert client.get(f"/api/ai/conversations/{conversation_id}").status_code == 404
    assert client.delete(f"/api/ai/conversations/{conversation_id}").status_code == 404
    assert client.get("/api/ai/conversations").json() == []


def test_requires_ai_permission(client: TestClient, allowed: dict[str, bool]) -> None:
    allowed["value"] = False
    assert client.get("/api/ai/conversations").status_code == 403
    assert client.post("/api/ai/conversations", json=BODY).status_code == 403


def test_rejects_unknown_fields_and_full_proposal_payload(client: TestClient) -> None:
    assert client.post("/api/ai/conversations", json={**BODY, "extra": 1}).status_code == 422
    leaky = {
        **BODY,
        "messages": [
            {
                "role": "assistant",
                "content": "x",
                "proposal": {"kind": "workflow", "summary": "s", "canvas_nodes": []},
            }
        ],
    }
    assert client.post("/api/ai/conversations", json=leaky).status_code == 422


def test_too_large_is_413(client: TestClient) -> None:
    big = {
        **BODY,
        "messages": [{"role": "user", "content": "x" * 19000} for _ in range(12)],
    }
    response = client.post("/api/ai/conversations", json=big)
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "ai_conversation_too_large"
