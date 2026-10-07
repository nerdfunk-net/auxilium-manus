"""TestClient coverage for POST /git/{repo_id}/preview-devices with device_mapping."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.auth import get_current_user, verify_token
from core.database import get_db
from routers.git import devices as devices_router
from services.auth.rbac_service import RBACService


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(RBACService, "has_permission", lambda self, *_a, **_k: True)
    (tmp_path / "d.yaml").write_text("devices:\n  - device_name: r1\n    site: City A\n")
    app = FastAPI()
    app.include_router(devices_router.router, prefix="/api")
    app.dependency_overrides[verify_token] = lambda: {"sub": "t", "user_id": 1}
    app.dependency_overrides[get_current_user] = lambda: {"sub": "t", "user_id": 1}
    app.dependency_overrides[get_db] = lambda: MagicMock()
    with (
        patch.object(
            devices_router.GitRepositoryService,
            "get_repository",
            return_value={"name": "r"},
        ),
        patch("services.git.device_service.clone_or_pull", return_value=tmp_path),
    ):
        yield TestClient(app)


def test_preview_with_mapping_returns_mapped_devices_and_keys(client) -> None:
    resp = client.post(
        "/api/git/1/preview-devices",
        json={
            "filename_pattern": "*.yaml",
            "device_mapping": [
                {"source": "device_name", "target": "name"},
                {"source": "site", "target": "location.name"},
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["devices"] == [{"name": "r1", "location": {"name": "City A"}}]
    assert body["available_keys"] == ["device_name", "site"]


def test_preview_invalid_mapping_is_400(client) -> None:
    resp = client.post(
        "/api/git/1/preview-devices",
        json={
            "filename_pattern": "*.yaml",
            "device_mapping": [{"source": "a", "target": "bogus"}],
        },
    )
    assert resp.status_code == 400


def test_preview_csv_multiline(client, tmp_path) -> None:
    (tmp_path / "d.csv").write_text("name;interface_name\nr1;\nr1;Eth0\nr1;Eth1\n")
    resp = client.post(
        "/api/git/1/preview-devices",
        json={
            "filename_pattern": "*.csv",
            "file_format": "csv",
            "csv_multiline": True,
            "device_mapping": [
                {"source": "name", "target": "name"},
                {"source": "interface_name", "target": "interfaces.name"},
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["devices"]) == 1
    assert [i["name"] for i in body["devices"][0]["interfaces"]] == ["Eth0", "Eth1"]
    assert body["available_keys"] == ["interface_name", "name"]


def test_preview_bad_delimiter_is_400(client) -> None:
    resp = client.post(
        "/api/git/1/preview-devices",
        json={"filename_pattern": "*.csv", "file_format": "csv", "csv_delimiter": "abc"},
    )
    assert resp.status_code == 400
