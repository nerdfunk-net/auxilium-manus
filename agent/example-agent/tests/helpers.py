"""Shared test helpers: a config, a registry with sample handlers and request envelopes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from manus_agent.config import AgentConfig
from manus_agent.envelope import open_envelope, seal
from manus_agent.registry import HandlerRegistry, builtin_registry

SECRET = "t" * 40
AGENT = "geo-agent"
NOW = 1_700_000_000


def make_config(**overrides: Any) -> AgentConfig:
    values: dict[str, Any] = {
        "agent_id": AGENT,
        "secret": SECRET,
        "http_host": "127.0.0.1",
        "http_port": 8080,
        "redis_url": None,
        "handlers_dir": Path("handlers"),
        "max_concurrency": 4,
        "max_body_bytes": 1_048_576,
        "max_response_bytes": 1_048_576,
        "loglevel": "INFO",
    }
    values.update(overrides)
    return AgentConfig(**values)


def make_registry() -> HandlerRegistry:
    registry = builtin_registry()
    registry.register("upper", lambda params, inputs: {"v": inputs["attributes"]["x"].upper()})

    async def slow(params: dict, inputs: dict) -> dict:
        await asyncio.sleep(params.get("seconds", 5))
        return {"done": True}

    def boom(params: dict, inputs: dict) -> dict:
        raise KeyError("site")

    registry.register("slow", slow)
    registry.register("boom", boom)
    registry.register("not_a_dict", lambda params, inputs: ["list"])
    registry.register("not_json", lambda params, inputs: {"v": object()})
    return registry


def request_envelope(
    handler: str = "upper",
    *,
    inputs: dict | None = None,
    params: dict | None = None,
    command_id: str = "cmd-1",
    now: int = NOW,
    ttl: int = 30,
    secret: str = SECRET,
    agent_id: str = AGENT,
    payload: dict | None = None,
) -> dict[str, Any]:
    body = payload or {
        "handler": handler,
        "params": params or {},
        "inputs": inputs if inputs is not None else {"attributes": {"x": "berlin"}, "content": {}},
    }
    return seal(
        body,
        secret=secret,
        agent_id=agent_id,
        command_id=command_id,
        direction="request",
        ttl_seconds=ttl,
        now=now,
    )


def open_response(envelope: dict, command_id: str = "cmd-1", now: int = NOW) -> dict[str, Any]:
    return open_envelope(
        envelope,
        secret=SECRET,
        expected_agent_id=AGENT,
        expected_direction="response",
        expected_command_id=command_id,
        now=now,
    ).payload
