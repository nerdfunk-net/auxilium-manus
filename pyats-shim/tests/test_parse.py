"""Tests for POST /v1/parse and its underlying _parse_one helper.

Guarded by importorskip: app.parse lazily imports genie.conf.base.Device
inside _parse_one, so the module itself always imports cleanly, but
exercising the actual parse logic requires genie -- which isn't installed in
every environment that runs the rest of the shim's test suite (see
requirements-dev.txt). This file is expected to run inside the shim's own
container/venv, where pyats[full] (and therefore genie) is installed; it is
fully skipped elsewhere, the same way tests/test_diff.py is.
"""

from __future__ import annotations

import pytest

pytest.importorskip("genie")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.parse import _parse_one, router  # noqa: E402

_SHOW_VERSION_OUTPUT = """Cisco IOS XE Software, Version 16.09.03
Cisco IOS Software [Fuji], Catalyst L3 Switch Software (CAT9K_IOSXE), Version 16.9.3
"""


@pytest.fixture(autouse=True)
def _shim_token(monkeypatch):
    monkeypatch.setenv("PYATS_SHIM_TOKEN", "test-token")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _auth_headers():
    return {"Authorization": "Bearer test-token"}


def test_parse_one_returns_parsed_dict_for_known_command():
    result = _parse_one(os_name="iosxe", command="show version", output=_SHOW_VERSION_OUTPUT)
    assert result.error is None
    assert isinstance(result.parsed, dict)


def test_parse_one_returns_error_for_unknown_command():
    result = _parse_one(os_name="iosxe", command="show frobnicate", output="nonsense output")
    assert result.parsed is None
    assert result.error is not None


def test_route_parses_known_command(client):
    response = client.post(
        "/v1/parse",
        json={
            "devices": {
                "dev1": {
                    "os": "iosxe",
                    "commands": [{"command": "show version", "output": _SHOW_VERSION_OUTPUT}],
                }
            }
        },
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    entry = body["results"]["dev1"]["commands"]["show version"]
    assert entry["error"] is None
    assert isinstance(entry["parsed"], dict)


def test_route_reports_per_command_error_without_failing_request(client):
    response = client.post(
        "/v1/parse",
        json={
            "devices": {
                "dev1": {
                    "os": "iosxe",
                    "commands": [{"command": "show frobnicate", "output": "nonsense"}],
                }
            }
        },
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    entry = response.json()["results"]["dev1"]["commands"]["show frobnicate"]
    assert entry["parsed"] is None
    assert entry["error"] is not None


def test_route_handles_mixed_success_and_failure_across_devices(client):
    response = client.post(
        "/v1/parse",
        json={
            "devices": {
                "dev1": {
                    "os": "iosxe",
                    "commands": [{"command": "show version", "output": _SHOW_VERSION_OUTPUT}],
                },
                "dev2": {
                    "os": "iosxe",
                    "commands": [{"command": "show frobnicate", "output": "nonsense"}],
                },
            }
        },
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    results = response.json()["results"]
    assert results["dev1"]["commands"]["show version"]["error"] is None
    assert results["dev2"]["commands"]["show frobnicate"]["error"] is not None


def test_route_missing_bearer_token_rejected(client):
    response = client.post(
        "/v1/parse",
        json={"devices": {"dev1": {"os": "iosxe", "commands": [{"command": "x", "output": "y"}]}}},
    )
    assert response.status_code == 401


def test_route_wrong_bearer_token_rejected(client):
    response = client.post(
        "/v1/parse",
        json={"devices": {"dev1": {"os": "iosxe", "commands": [{"command": "x", "output": "y"}]}}},
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401


if __name__ == "__main__":
    pytest.main([__file__])
