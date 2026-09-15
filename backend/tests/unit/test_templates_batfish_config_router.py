"""TestClient tests for POST/PUT /templates' `batfish_config` field --
specifically the "generic" ad-hoc question sentinel (Options modal's "Custom
Question..." entry) and its `generic_question_name` companion field, added
alongside the ad-hoc allow-listed query surface (see
doc/BATFISH_INTEGRATION.md "Generic ad-hoc questions"). Regression coverage
for a bug caught in review: models.templates.BatfishQueryConfig originally
kept its closed `Literal["routes", "reachability", "testFilters"]` question
type with no `generic_question_name` field, so saving a template with a
Custom Question configured 422'd before ever reaching the service.
"""

from __future__ import annotations

from collections.abc import Iterator
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from routers.templates import _service
from routers.templates import router as templates_router
from services.auth.rbac_service import RBACService


def _make_user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _override_db() -> Iterator[MagicMock]:
    yield MagicMock()


def _template_dict(**overrides: object) -> dict:
    base = {
        "id": 1,
        "name": "tpl",
        "source": "webeditor",
        "template_type": "jinja2",
        "category": "netmiko",
        "description": None,
        "notes": None,
        "content": "",
        "variables": {},
        "pre_run_commands": [],
        "pre_run_use_textfsm": False,
        "nautobot_attributes": [],
        "credential_id": None,
        "batfish_config": None,
        "created_by": "tester",
        "is_active": True,
        "created_at": "2026-01-01T00:00:00+00:00",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


@pytest.fixture
def service() -> MagicMock:
    return MagicMock()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, service: MagicMock) -> Iterator[TestClient]:
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    app = FastAPI()
    app.include_router(templates_router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: {"sub": "tester", "user_id": 1}
    app.dependency_overrides[get_current_user] = _make_user
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[_service] = lambda: service
    with TestClient(app) as test_client:
        yield test_client


def _generic_batfish_config() -> dict:
    return {
        "enabled": True,
        "source_id": "lab",
        "network": "net",
        "snapshot": None,
        "question": "generic",
        "generic_question_name": "bgpPeerConfiguration",
        "params": {"nodes": "R1"},
    }


def test_create_accepts_generic_question_without_422(
    client: TestClient, service: MagicMock
) -> None:
    service.create_template.return_value = _template_dict(
        batfish_config=_generic_batfish_config()
    )

    response = client.post(
        "/api/templates",
        json={"name": "tpl", "batfish_config": _generic_batfish_config()},
    )

    assert response.status_code == 201
    forwarded = service.create_template.call_args.kwargs["batfish_config"]
    assert forwarded["question"] == "generic"
    assert forwarded["generic_question_name"] == "bgpPeerConfiguration"


def test_update_accepts_generic_question_without_422(
    client: TestClient, service: MagicMock
) -> None:
    service.update_template.return_value = _template_dict(
        batfish_config=_generic_batfish_config()
    )

    response = client.put(
        "/api/templates/1",
        json={"batfish_config": _generic_batfish_config()},
    )

    assert response.status_code == 200
    forwarded = service.update_template.call_args.kwargs["batfish_config"]
    assert forwarded["question"] == "generic"
    assert forwarded["generic_question_name"] == "bgpPeerConfiguration"


def test_typed_question_still_accepted(client: TestClient, service: MagicMock) -> None:
    typed_config = {
        **_generic_batfish_config(),
        "question": "routes",
        "generic_question_name": None,
    }
    service.create_template.return_value = _template_dict(batfish_config=typed_config)

    response = client.post(
        "/api/templates", json={"name": "tpl", "batfish_config": typed_config}
    )

    assert response.status_code == 201
    assert service.create_template.call_args.kwargs["batfish_config"]["question"] == "routes"


def test_invalid_question_still_rejected(client: TestClient, service: MagicMock) -> None:
    bad_config = {**_generic_batfish_config(), "question": "dropTables"}

    response = client.post(
        "/api/templates", json={"name": "tpl", "batfish_config": bad_config}
    )

    assert response.status_code == 422
    service.create_template.assert_not_called()
