"""``DbClientDataReader`` checks ``client_data:read`` on every call and only then reads."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest

from services.ai_assistant import client_data_reader as module
from services.ai_assistant.client_data_reader import ClientDataAccessError, DbClientDataReader


@pytest.fixture
def wired(monkeypatch):
    state: dict[str, Any] = {"allowed": True, "checked": [], "service": MagicMock()}

    class FakeRbac:
        def __init__(self, db: Any) -> None:
            pass

        def has_permission(self, user_id: int, resource: str, action: str) -> bool:
            state["checked"].append((user_id, resource, action))
            return state["allowed"]

    @contextmanager
    def session():
        yield MagicMock()

    monkeypatch.setattr(module, "RBACService", FakeRbac)
    monkeypatch.setattr(module, "SessionLocal", session)
    monkeypatch.setattr(module, "ClientDataService", lambda db: state["service"])
    state["service"].get_client_data.return_value = ([{"device_name": "sw"}], 1)
    state["service"].get_client_history.return_value = {"mac_history": []}
    state["service"].get_collections.return_value = [{"device_name": "sw"}]
    return state


def test_every_call_checks_the_permission_and_passes_the_filters(wired) -> None:
    reader = DbClientDataReader(7)

    rows, total = asyncio.run(reader.observations(mac_address="aabb", exact=True))
    history = asyncio.run(reader.history(mac_address="aabb", limit=5))
    coverage = asyncio.run(reader.coverage())

    assert (rows, total) == ([{"device_name": "sw"}], 1)
    assert history == {"mac_history": []}
    assert coverage == [{"device_name": "sw"}]
    assert wired["checked"] == [(7, "client_data", "read")] * 3
    wired["service"].get_client_data.assert_called_once_with(mac_address="aabb", exact=True)
    wired["service"].get_client_history.assert_called_once_with(mac_address="aabb", limit=5)


@pytest.mark.parametrize("call", ["observations", "history", "coverage"])
def test_without_the_permission_nothing_is_read(wired, call: str) -> None:
    wired["allowed"] = False

    with pytest.raises(ClientDataAccessError):
        asyncio.run(getattr(DbClientDataReader(7), call)())

    wired["service"].get_client_data.assert_not_called()
    wired["service"].get_client_history.assert_not_called()
    wired["service"].get_collections.assert_not_called()
