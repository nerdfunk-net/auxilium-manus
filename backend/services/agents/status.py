"""What the heartbeat of a Redis agent says: online, version and the handlers it offers.

The agent writes the hash at ``manus-agent:{agent_id}:hb`` (see redis_transport) and renews its
TTL; no hash means offline. HTTP agents have no heartbeat, so their status is unknown and the
UI points at the encrypted test-connection instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import redis.asyncio as aioredis

from services.agents.redis_transport import heartbeat_key
from services.agents.source_config_service import AgentConnection

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentStatus:
    transport: str
    online: bool | None
    message: str
    version: str | None = None
    handlers: list[str] = field(default_factory=list)
    last_heartbeat: int | None = None


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value))
    except ValueError:
        return None


async def read_status(
    connection: AgentConnection, *, redis: aioredis.Redis | None
) -> AgentStatus:
    if connection.transport != "redis" or redis is None:
        return AgentStatus(
            transport=connection.transport,
            online=None,
            message="HTTP agents have no heartbeat; use Test connection.",
        )
    try:
        beat = await redis.hgetall(heartbeat_key(connection.agent_id))  # type: ignore[misc]
    except Exception:
        logger.warning("agent status: could not read heartbeat for %s", connection.source_id)
        return AgentStatus(
            transport="redis", online=None, message="Could not read the heartbeat from Redis."
        )
    if not beat:
        return AgentStatus(
            transport="redis",
            online=False,
            message="No heartbeat: the agent is not running or cannot reach Redis.",
        )
    handlers = [name for name in str(beat.get("handlers", "")).split(",") if name]
    return AgentStatus(
        transport="redis",
        online=True,
        message="Agent is online.",
        version=str(beat["version"]) if beat.get("version") else None,
        handlers=handlers,
        last_heartbeat=_int_or_none(beat.get("last_heartbeat")),
    )
