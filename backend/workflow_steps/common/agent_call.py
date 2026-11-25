"""What the two agent steps (``route-to-agent``, ``get-from-agent``) share (W8-07).

Request parsing (handler name, agent source id, timeout), the "timeout above the agent's maximum"
check and the lifetime of the agent client. Each step keeps its own order of checks and its own
``StepConfig``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import service_factory
from services.agents.client import HANDLER_NAME_PATTERN, AgentClient
from services.agents.source_config_service import AgentConnection
from workflow_steps.common.step_flags import parse_int_flag

TIMEOUT_RANGE = (1, 600)


def parse_handler(config: dict[str, Any], *, step_id: str) -> str:
    handler = str(config.get("handler") or "").strip()
    if not handler:
        raise ValueError(f"{step_id}: handler is required")
    if not HANDLER_NAME_PATTERN.fullmatch(handler):
        raise ValueError(f"{step_id}: handler {handler!r} is not a valid handler name")
    return handler


def parse_agent_source_id(config: dict[str, Any], *, step_id: str) -> str:
    source_id = str(config.get("agent_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{step_id}: agent_source_id is not configured")
    return source_id


def parse_timeout(config: dict[str, Any], *, default: int) -> int:
    return parse_int_flag(
        config,
        "timeout_seconds",
        default=default,
        minimum=TIMEOUT_RANGE[0],
        maximum=TIMEOUT_RANGE[1],
    )


def check_timeout(connection: AgentConnection, timeout_seconds: int, *, step_id: str) -> None:
    """Refuse a step timeout above the agent's maximum.

    Not clamped silently: a step set to 120 s against a 60 s agent would fail every device at
    60 s as "agent_timeout" with nothing pointing at the setting.
    """
    if timeout_seconds > connection.max_timeout_seconds:
        raise ValueError(
            f"{step_id}: timeout_seconds ({timeout_seconds}) is above the maximum of "
            f"{connection.max_timeout_seconds} seconds set on agent {connection.source_id!r}; "
            "lower the step timeout or raise the agent's max timeout in Settings -> Sources"
        )


@asynccontextmanager
async def agent_client(connection: AgentConnection) -> AsyncIterator[AgentClient]:
    """The client of ``connection``, closed when the block ends (also on cancellation)."""
    client = service_factory.build_agent_client(connection)
    try:
        yield client
    finally:
        await client.aclose()
