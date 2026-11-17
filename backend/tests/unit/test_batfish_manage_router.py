"""FastAPI TestClient tests for the Batfish manage endpoints
(routers/sources/batfish/manage.py and the networks-summary route)."""

from __future__ import annotations

from collections.abc import Iterator
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from _auth_helpers import make_auth_db, token_payload
from fastapi import FastAPI
from fastapi.testclient import TestClient

import service_factory
from core.auth import get_current_user, verify_token
from core.database import get_db
from core.models.users import User
from dependencies import get_batfish_preview_service, get_batfish_source_config_service
from routers.sources.batfish import (
    batfish_source_discovery_router,
    batfish_source_manage_router,
)
from services.auth.rbac_service import RBACService
from services.batfish.common.exceptions import BatfishAPIError

BASE = "/api/sources/batfish/lab"


def _user() -> User:
    user = User(username="tester", password_hash="hash", is_active=True)
    user.id = 1
    return user


def _db() -> Iterator[MagicMock]:
    yield make_auth_db()


def _setup(
    monkeypatch: pytest.MonkeyPatch, *, allowed: set[str] | None = None
) -> tuple[TestClient, MagicMock, MagicMock]:
    """``allowed``: permissions ("resource:action") granted; None grants everything."""
    app = FastAPI()
    app.include_router(batfish_source_discovery_router, prefix="/api")
    app.include_router(batfish_source_manage_router, prefix="/api")
    monkeypatch.setattr(
        RBACService,
        "has_permission",
        lambda self, _uid, res, act: allowed is None or f"{res}:{act}" in allowed,
    )
    config = MagicMock()
    config.resolve_connection.return_value = MagicMock()
    preview = MagicMock()
    batfish = MagicMock()
    batfish.list_networks = AsyncMock(return_value=["net-a", "net-b"])
    batfish.delete_network = AsyncMock()
    batfish.delete_snapshot = AsyncMock()
    batfish.list_snapshots = AsyncMock(return_value=["s1", "s2"])
    batfish.list_snapshots_with_metadata = AsyncMock(
        return_value=[{"name": "s1", "metadata": {}}, {"name": "s2", "metadata": {}}]
    )
    monkeypatch.setattr(service_factory, "get_batfish_app_service", lambda: batfish)
    app.dependency_overrides[get_batfish_source_config_service] = lambda: config
    app.dependency_overrides[get_batfish_preview_service] = lambda: preview
    app.dependency_overrides[verify_token] = lambda: token_payload()
    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db
    return TestClient(app), batfish, preview


def test_summary_counts_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, _ = _setup(monkeypatch)
    response = client.get(f"{BASE}/networks-summary")
    assert response.status_code == 200
    assert response.json()["networks"] == [
        {"name": "net-a", "snapshot_count": 2, "unavailable": False, "latest_snapshot_at": None},
        {"name": "net-b", "snapshot_count": 2, "unavailable": False, "latest_snapshot_at": None},
    ]


def test_summary_reports_newest_snapshot_date(monkeypatch: pytest.MonkeyPatch) -> None:
    client, batfish, _ = _setup(monkeypatch)
    batfish.list_networks = AsyncMock(return_value=["net-a"])
    batfish.list_snapshots_with_metadata = AsyncMock(
        return_value=[
            {"name": "old", "metadata": {"creationTimestamp": "2026-01-01T00:00:00Z"}},
            {"name": "new", "metadata": {"creationTimestamp": "2026-11-01T10:00:00Z"}},
            {"name": "nodate", "metadata": {}},
        ]
    )
    body = client.get(f"{BASE}/networks-summary").json()
    # the nameless row is not counted: the picker would not show it either
    assert body["networks"] == [
        {
            "name": "net-a",
            "snapshot_count": 3,
            "unavailable": False,
            "latest_snapshot_at": "2026-11-01T10:00:00Z",
        }
    ]


def test_summary_survives_null_metadata_and_one_failing_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, batfish, _ = _setup(monkeypatch)

    async def listing(_conn, *, batfish_network):
        if batfish_network == "net-a":
            raise BatfishAPIError("coordinator hiccup")
        return [{"name": "s1", "metadata": None}, {"name": "", "metadata": {}}]

    batfish.list_snapshots_with_metadata = listing
    response = client.get(f"{BASE}/networks-summary")
    assert response.status_code == 200
    nets = {n["name"]: n for n in response.json()["networks"]}
    assert nets["net-a"]["unavailable"] is True
    assert nets["net-a"]["snapshot_count"] is None
    assert nets["net-b"] == {
        "name": "net-b",
        "snapshot_count": 1,
        "unavailable": False,
        "latest_snapshot_at": None,
    }


# Names the body validator rejects (the URL layer normalises "/" and a bare ".." itself).
@pytest.mark.parametrize("bad", ["a/b", "..", "x..y", "a\\b", "n" * 256])
def test_unsafe_snapshot_names_in_body_are_rejected(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    client, batfish, _ = _setup(monkeypatch)
    post = client.post(f"{BASE}/networks/net-a/snapshots/delete", json={"snapshots": [bad]})
    assert post.status_code == 422
    batfish.delete_snapshot.assert_not_called()


# Path segments that still reach the handler: its own check answers 400 before any call.
@pytest.mark.parametrize("bad", ["x..y", "a%5Cb", "n" * 256])
def test_unsafe_path_names_are_rejected_before_any_coordinator_call(
    monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    client, batfish, _ = _setup(monkeypatch)
    assert client.delete(f"{BASE}/networks/{bad}").status_code == 400
    assert client.get(f"{BASE}/networks/net-a/snapshots/{bad}/devices").status_code == 400
    assert (
        client.post(
            f"{BASE}/networks/{bad}/snapshots/delete", json={"snapshots": ["s1"]}
        ).status_code
        == 400
    )
    batfish.list_networks.assert_not_called()
    batfish.delete_network.assert_not_called()
    batfish.delete_snapshot.assert_not_called()


def test_delete_snapshots_batch_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    client, batfish, _ = _setup(monkeypatch)
    url = f"{BASE}/networks/net-a/snapshots/delete"
    assert client.post(url, json={"snapshots": [f"s{i}" for i in range(51)]}).status_code == 422
    batfish.delete_snapshot.assert_not_called()


def test_deletes_log_the_acting_user(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    client, _, _ = _setup(monkeypatch)
    with caplog.at_level("INFO", logger="routers.sources.batfish.manage"):
        client.delete(f"{BASE}/networks/net-a")
        client.post(f"{BASE}/networks/net-a/snapshots/delete", json={"snapshots": ["s1"]})
    messages = [r.getMessage() for r in caplog.records]
    assert any("User 1 deleted Batfish network" in m for m in messages)
    assert any("User 1 deleted 1 Batfish snapshot" in m for m in messages)


def test_delete_network_needs_write(monkeypatch: pytest.MonkeyPatch) -> None:
    client, batfish, _ = _setup(monkeypatch, allowed={"sources.batfish:read"})
    response = client.delete(f"{BASE}/networks/net-a")
    assert response.status_code == 403
    batfish.delete_network.assert_not_called()


def test_delete_network_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client, batfish, _ = _setup(monkeypatch)
    response = client.delete(f"{BASE}/networks/net-a")
    assert response.status_code == 204
    assert batfish.delete_network.await_args.kwargs["network"] == "net-a"


def test_delete_unknown_network_is_400_and_deletes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, batfish, _ = _setup(monkeypatch)
    response = client.delete(f"{BASE}/networks/nope")
    assert response.status_code == 400
    batfish.delete_network.assert_not_called()
    batfish.list_snapshots_with_metadata.assert_not_called()


def test_delete_network_api_error_is_sanitized_502(monkeypatch: pytest.MonkeyPatch) -> None:
    client, batfish, _ = _setup(monkeypatch)
    batfish.delete_network.side_effect = BatfishAPIError("secret internal detail")
    response = client.delete(f"{BASE}/networks/net-a")
    assert response.status_code == 502
    assert "secret internal detail" not in response.text


def test_delete_snapshots_reports_deleted_and_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    client, batfish, _ = _setup(monkeypatch)
    response = client.post(
        f"{BASE}/networks/net-a/snapshots/delete", json={"snapshots": ["s1", "ghost", "s1"]}
    )
    assert response.status_code == 200
    assert response.json() == {"deleted": ["s1"], "failed": ["ghost"]}
    assert batfish.delete_snapshot.await_count == 1


def test_delete_snapshots_partial_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client, batfish, _ = _setup(monkeypatch)
    batfish.delete_snapshot.side_effect = [None, BatfishAPIError("x")]
    response = client.post(
        f"{BASE}/networks/net-a/snapshots/delete", json={"snapshots": ["s1", "s2"]}
    )
    assert response.json() == {"deleted": ["s1"], "failed": ["s2"]}


def test_delete_snapshots_rejects_empty_and_unknown_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, _ = _setup(monkeypatch)
    url = f"{BASE}/networks/net-a/snapshots/delete"
    assert client.post(url, json={"snapshots": []}).status_code == 422
    assert client.post(url, json={"snapshots": ["s1"], "x": 1}).status_code == 422


def test_delete_snapshots_needs_write(monkeypatch: pytest.MonkeyPatch) -> None:
    client, batfish, _ = _setup(monkeypatch, allowed={"sources.batfish:query"})
    response = client.post(f"{BASE}/networks/net-a/snapshots/delete", json={"snapshots": ["s1"]})
    assert response.status_code == 403
    batfish.delete_snapshot.assert_not_called()


def test_devices_groups_ips_by_node(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, preview = _setup(monkeypatch)
    preview.run_snapshot_devices = AsyncMock(
        return_value=SimpleNamespace(
            snapshot="s1",
            node_rows=[{"Node": "r2"}, {"Node": "r1"}],
            ip_rows=[
                {"Node": "r1", "IP": "10.0.0.1"},
                {"Node": "r1", "IP": "10.0.0.1"},
                {"Node": "r1", "IP": "10.0.1.1"},
            ],
            unavailable={},
            truncated_sections=(),
        )
    )
    response = client.get(f"{BASE}/networks/net-a/snapshots/s1/devices")
    assert response.status_code == 200
    assert response.json()["devices"] == [
        {"device": "r1", "ip_addresses": ["10.0.0.1", "10.0.1.1"]},
        {"device": "r2", "ip_addresses": []},
    ]
    assert response.json()["ips_unavailable"] is False


def test_devices_flags_unavailable_ips(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, preview = _setup(monkeypatch)
    preview.run_snapshot_devices = AsyncMock(
        return_value=SimpleNamespace(
            snapshot="s1",
            node_rows=[{"Node": "r1"}],
            ip_rows=[],
            unavailable={"ips": "X"},
            truncated_sections=("ips",),
        )
    )
    body = client.get(f"{BASE}/networks/net-a/snapshots/s1/devices").json()
    assert body["ips_unavailable"] is True
    assert body["truncated"] is True


def test_devices_needs_query_not_read(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, _ = _setup(monkeypatch, allowed={"sources.batfish:read"})
    assert client.get(f"{BASE}/networks/net-a/snapshots/s1/devices").status_code == 403


def test_devices_unknown_snapshot_is_400(monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, preview = _setup(monkeypatch)
    preview.run_snapshot_devices = AsyncMock()
    assert client.get(f"{BASE}/networks/net-a/snapshots/ghost/devices").status_code == 400
    preview.run_snapshot_devices.assert_not_called()
