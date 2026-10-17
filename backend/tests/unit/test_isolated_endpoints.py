"""S4-07 / S5-12: caller-supplied programs run in a killable child, not in the API process."""

from __future__ import annotations

import asyncio
import time

import pytest
from _ai_helpers import assert_within_budget
from _auth_helpers import make_auth_db, token_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from core.regex_isolated import run_regex
from routers.templates import router as templates_router
from routers.workflow_update_attribute import router as attribute_router
from routers.workflow_update_content import router as content_router
from services.auth.rbac_service import RBACService


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    for router in (templates_router, content_router, attribute_router):
        app.include_router(router, prefix="/api")
    user = User(username="t", password_hash="h", is_active=True)
    user.id = 1
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[get_db] = lambda: make_auth_db()
    with TestClient(app) as test_client:
        yield test_client


def test_render_works(client) -> None:
    response = client.post(
        "/api/templates/render",
        json={"template_content": "hello {{ name }}", "variables": {"name": "r1"}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["rendered_content"] == "hello r1"
    assert response.json()["variables_used"] == ["name"]


def test_undefined_variable_is_a_400(client) -> None:
    response = client.post("/api/templates/render", json={"template_content": "{{ missing }}"})
    assert response.status_code == 400


def test_render_memory_bomb_is_stopped(client) -> None:
    def call() -> None:
        response = client.post(
            "/api/templates/render", json={"template_content": "{{ 'A' * 4000000000 }}"}
        )
        assert response.status_code == 400

    assert_within_budget(call, 6.0)


def test_render_cpu_bomb_is_stopped(client) -> None:
    template = "{% for i in range(100000) %}{% for j in range(100000) %}x{% endfor %}{% endfor %}"

    def call() -> None:
        response = client.post("/api/templates/render", json={"template_content": template})
        assert response.status_code == 400

    assert_within_budget(call, 8.0)


def test_oversized_template_is_422(client) -> None:
    response = client.post(
        "/api/templates/render", json={"template_content": "x" * 200_001, "variables": {}}
    )
    assert response.status_code == 422


def test_redos_probe_is_killed(client) -> None:
    body = {
        "sample_text": "a" * 40 + "b",
        "pattern": "(a+)+$",
        "replacement": "x",
        "regex_flags": {},
        "replace_all": True,
    }

    def call() -> None:
        response = client.post("/api/workflow-steps/update-content/probe", json=body)
        assert response.status_code == 400
        assert "stopped" in response.json()["detail"]

    assert_within_budget(call, 4.0)


def test_normal_probe_still_works(client) -> None:
    body = {
        "sample_text": "interface Gi0/1",
        "pattern": "Gi(\\d)",
        "replacement": "Te\\1",
        "regex_flags": {},
        "replace_all": True,
    }
    response = client.post("/api/workflow-steps/update-content/probe", json=body)
    assert response.status_code == 200
    assert response.json() == {"matched": True, "match_count": 1, "updated_text": "interface Te0/1"}
    attr = client.post(
        "/api/workflow-steps/update-attribute/probe",
        json={"sample_text": "ver 15.2", "pattern": "ver (\\S+)", "destination_template": "\\1"},
    )
    assert attr.status_code == 200 and attr.json()["destination_value"] == "15.2"


def test_invalid_regex_is_a_400_with_message(client) -> None:
    response = client.post(
        "/api/workflow-steps/update-content/probe",
        json={"sample_text": "x", "pattern": "(", "replacement": "", "regex_flags": {}},
    )
    assert response.status_code == 400
    assert "invalid regular expression" in response.json()["detail"]


def test_regex_job_does_not_stall_the_event_loop() -> None:
    """The S5 correction: a catastrophic match must not hold the GIL of the API process."""

    async def scenario() -> float:
        longest = 0.0
        stop = False

        async def ticker() -> None:
            nonlocal longest
            last = time.perf_counter()
            while not stop:
                await asyncio.sleep(0.02)
                now = time.perf_counter()
                longest = max(longest, now - last)
                last = now

        task = asyncio.create_task(ticker())
        outcome = await run_regex(
            {
                "op": "replace",
                "text": "a" * 40 + "b",
                "pattern": "(a+)+$",
                "replacement": "x",
                "flags": {},
                "replace_all": True,
            },
            timeout=1.5,
        )
        stop = True
        await task
        assert not outcome.ok
        return longest

    assert asyncio.run(scenario()) < 0.5


def test_child_environment_is_empty(monkeypatch) -> None:
    """S5-12: the worker gets no SECRET_KEY / database / Hatchet secrets."""
    import core.regex_isolated as isolated

    seen: dict = {}
    real = asyncio.create_subprocess_exec

    async def spy(*args, **kwargs):
        seen["env"] = kwargs.get("env")
        return await real(*args, **kwargs)

    monkeypatch.setattr(isolated.asyncio, "create_subprocess_exec", spy)
    asyncio.run(
        run_regex(
            {
                "op": "probe",
                "text": "a",
                "pattern": "a",
                "destination_template": "b",
                "flags": {},
            }
        )
    )
    assert seen["env"] == {}


def _alias_bomb() -> str:
    lines = ["a: &a [x, x, x, x, x, x, x, x, x]"]
    previous = "a"
    for index in range(6):
        name = chr(ord("b") + index)
        lines.append(f"{name}: &{name} [" + ", ".join(f"*{previous}" for _ in range(9)) + "]")
        previous = name
    return "\n".join(lines)


def test_yaml_alias_bomb_is_rejected(client) -> None:
    payload = _alias_bomb()
    assert len(payload) < 500
    response = client.post(
        "/api/templates/parse-structured", json={"content": payload, "format": "yaml"}
    )
    assert response.status_code == 422
    assert len(response.text) < 1024
    assert "anchors and aliases" in response.json()["detail"]


def test_plain_yaml_still_parses_and_oversized_is_422(client) -> None:
    ok = client.post(
        "/api/templates/parse-structured", json={"content": "a: 1\nb: [1, 2]\n", "format": "yaml"}
    )
    assert ok.status_code == 200 and ok.json()["parsed"] == {"a": 1, "b": [1, 2]}
    big = client.post("/api/templates/parse-structured", json={"content": "x" * 1_000_001})
    assert big.status_code == 422
