"""The request parsing and client lifetime the two agent steps share (W8-07)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.agents.source_config_service import AgentConnection
from workflow_steps.common.agent_call import (
    TIMEOUT_RANGE,
    agent_client,
    check_timeout,
    parse_agent_source_id,
    parse_handler,
    parse_timeout,
)


def _connection(max_timeout: int = 60) -> MagicMock:
    connection = MagicMock(spec=AgentConnection)
    connection.max_timeout_seconds = max_timeout
    connection.source_id = "agent-1"
    return connection


def test_handler_is_required_and_pattern_checked() -> None:
    assert parse_handler({"handler": "  scan  "}, step_id="st") == "scan"
    with pytest.raises(ValueError, match="^st: handler is required$"):
        parse_handler({"handler": "  "}, step_id="st")
    with pytest.raises(ValueError, match="^st: handler 'bad name' is not a valid handler name$"):
        parse_handler({"handler": "bad name"}, step_id="st")


def test_agent_source_id_is_required_and_stripped() -> None:
    assert parse_agent_source_id({"agent_source_id": " a1 "}, step_id="st") == "a1"
    for config in ({}, {"agent_source_id": None}, {"agent_source_id": "  "}):
        with pytest.raises(ValueError, match="^st: agent_source_id is not configured$"):
            parse_agent_source_id(config, step_id="st")


def test_timeout_default_and_bounds() -> None:
    assert TIMEOUT_RANGE == (1, 600)
    assert parse_timeout({}, default=30) == 30
    assert parse_timeout({"timeout_seconds": 600}, default=30) == 600
    assert parse_timeout({"timeout_seconds": 1}, default=30) == 1
    for bad in (0, 601):
        with pytest.raises(ValueError, match="timeout_seconds"):
            parse_timeout({"timeout_seconds": bad}, default=30)


def test_check_timeout_refuses_above_the_agents_maximum() -> None:
    check_timeout(_connection(60), 60, step_id="st")
    with pytest.raises(ValueError) as caught:
        check_timeout(_connection(60), 61, step_id="st")
    message = str(caught.value)
    assert message.startswith("st: timeout_seconds (61) is above the maximum of 60 seconds")
    assert "'agent-1'" in message
    assert "Settings -> Sources" in message


@pytest.mark.asyncio
async def test_agent_client_is_built_from_the_connection_and_always_closed() -> None:
    client = MagicMock()
    client.aclose = AsyncMock()
    connection = _connection()
    with patch("service_factory.build_agent_client", return_value=client) as build:
        async with agent_client(connection) as got:
            assert got is client
            client.aclose.assert_not_awaited()
        build.assert_called_once_with(connection)
        client.aclose.assert_awaited_once()

        client.aclose.reset_mock()
        with pytest.raises(RuntimeError, match="boom"):
            async with agent_client(connection):
                raise RuntimeError("boom")
        client.aclose.assert_awaited_once()

        client.aclose.reset_mock()
        with pytest.raises(asyncio.CancelledError):
            async with agent_client(connection):
                raise asyncio.CancelledError
        client.aclose.assert_awaited_once()
