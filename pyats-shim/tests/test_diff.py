"""Tests for POST /v1/diff and its underlying _compute_diff/_unwrap helpers.

Guarded by importorskip: app.diff lazily imports genie.utils.diff.Diff inside
_compute_diff, so the module itself always imports cleanly, but exercising the
actual diff logic requires genie -- which isn't installed in every environment
that runs the rest of the shim's test suite (see requirements-dev.txt). This
file is expected to run inside the shim's own container/venv, where
pyats[full] (and therefore genie) is installed; it is fully skipped elsewhere,
the same way tests/test_generic_script.py is skipped for pyats.
"""

from __future__ import annotations

import pytest

pytest.importorskip("genie")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.diff import _compute_diff, _unwrap, router  # noqa: E402


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


def test_unwrap_extracts_info_key():
    assert _unwrap({"info": {"a": 1}}) == {"a": 1}


def test_unwrap_falls_back_to_whole_dict_when_no_info_key():
    assert _unwrap({"a": 1}) == {"a": 1}


def test_compute_diff_identical_snapshots_report_no_diff():
    identical, diff_text = _compute_diff({"info": {"a": 1}}, {"info": {"a": 1}})
    assert identical is True
    assert diff_text.strip() == ""


def test_compute_diff_differing_snapshots_report_diff():
    identical, diff_text = _compute_diff({"info": {"a": 1}}, {"info": {"a": 2}})
    assert identical is False
    assert diff_text.strip() != ""


def test_compute_diff_unwraps_info_key_on_both_sides():
    identical, _ = _compute_diff({"info": {"a": 1}, "extra": "ignored"}, {"info": {"a": 1}})
    assert identical is True


def test_compute_diff_without_info_key_diffs_whole_dict():
    identical, diff_text = _compute_diff({"a": 1}, {"a": 2})
    assert identical is False
    assert diff_text.strip() != ""


def test_route_returns_diff_for_differing_snapshots(client):
    response = client.post(
        "/v1/diff",
        json={"snapshot_a": {"info": {"a": 1}}, "snapshot_b": {"info": {"a": 2}}},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["identical"] is False
    assert body["diff"] != ""


def test_route_returns_identical_for_matching_snapshots(client):
    response = client.post(
        "/v1/diff",
        json={"snapshot_a": {"info": {"a": 1}}, "snapshot_b": {"info": {"a": 1}}},
        headers=_auth_headers(),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["identical"] is True
    assert body["diff"] == ""


def test_route_returns_400_when_diff_raises(client, monkeypatch):
    def _boom(*_args, **_kwargs):
        raise RuntimeError("incompatible snapshot shapes")

    monkeypatch.setattr("app.diff._compute_diff", _boom)
    response = client.post(
        "/v1/diff",
        json={"snapshot_a": {"info": {}}, "snapshot_b": {"info": {}}},
        headers=_auth_headers(),
    )
    assert response.status_code == 400
    assert "incompatible snapshot shapes" in response.json()["detail"]


def test_route_missing_bearer_token_rejected(client):
    response = client.post(
        "/v1/diff", json={"snapshot_a": {"info": {}}, "snapshot_b": {"info": {}}}
    )
    assert response.status_code == 401


def test_route_wrong_bearer_token_rejected(client):
    response = client.post(
        "/v1/diff",
        json={"snapshot_a": {"info": {}}, "snapshot_b": {"info": {}}},
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 401
