"""Redis transport: a request list and one response list per command.

Keys, under ``manus-agent:{agent_id}:`` (the agent's ACL user is limited to this prefix)::

    req             list    the app RPUSHes sealed requests, the agent BLPOPs them
    resp:{cmd}      list    the agent RPUSHes the sealed response, the app BLPOPs it
    hb              hash    heartbeat the agent writes (expires, so absence means offline)

Compared with pub/sub, a request waits in the list until the agent takes it and a response
cannot be missed by subscribing late. A request that timed out is removed again, and the
envelope's own expiry makes an agent that comes back later discard anything stale.
"""

from __future__ import annotations

import json
import math
from typing import Any

import redis.asyncio as aioredis

from services.agents.exceptions import (
    AgentOfflineError,
    AgentTimeoutError,
    AgentTransportError,
)

KEY_PREFIX = "manus-agent"
MAX_RESPONSE_BYTES = 16 * 1_048_576  # same bound as the HTTP transport
_REQUEST_QUEUE_TTL_MARGIN = 60


def request_key(agent_id: str) -> str:
    return f"{KEY_PREFIX}:{agent_id}:req"


def response_key(agent_id: str, command_id: str) -> str:
    return f"{KEY_PREFIX}:{agent_id}:resp:{command_id}"


def heartbeat_key(agent_id: str) -> str:
    return f"{KEY_PREFIX}:{agent_id}:hb"


class RedisTransport:
    def __init__(self, client: aioredis.Redis, *, agent_id: str) -> None:
        self._redis = client
        self._agent_id = agent_id
        self._max_response_bytes = MAX_RESPONSE_BYTES

    async def call(self, envelope: dict[str, Any], *, timeout: float) -> dict[str, Any]:
        command_id = str(envelope["command_id"])
        raw = json.dumps(envelope, separators=(",", ":"))
        queue = request_key(self._agent_id)
        answer = response_key(self._agent_id, command_id)

        try:
            # Fail fast instead of waiting out the timeout for an agent that is not running.
            if not await self._redis.exists(heartbeat_key(self._agent_id)):
                raise AgentOfflineError("agent has no heartbeat (not running or no Redis access)")
            await self._redis.rpush(queue, raw)
            # One list serves every in-flight call, so its TTL must cover the longest request
            # still waiting in it: NX sets it on a fresh list, GT only ever extends it (a plain
            # EXPIRE would let a short call delete a long call's queued request). Needs Redis 7+.
            ttl = math.ceil(timeout) + _REQUEST_QUEUE_TTL_MARGIN
            await self._redis.expire(queue, ttl, nx=True)
            await self._redis.expire(queue, ttl, gt=True)
            try:
                popped = await self._redis.blpop([answer], timeout=timeout)
            finally:
                # The answer list is single-use; and if nobody took the request, withdraw it.
                await self._redis.lrem(queue, 1, raw)
                await self._redis.delete(answer)
        except (ConnectionError, OSError, aioredis.RedisError) as exc:
            raise AgentOfflineError("Redis is not reachable") from exc

        if popped is None:
            raise AgentTimeoutError("agent did not answer in time")
        # The Redis client has already read the value, so this cannot save memory by itself;
        # the agent enforces its own response limit (MANUS_AGENT_MAX_RESPONSE_BYTES). This
        # keeps an oversized value from being parsed and from reaching the step.
        if len(popped[1]) > self._max_response_bytes:
            raise AgentTransportError("agent response is too large")
        try:
            decoded = json.loads(popped[1])
        except ValueError as exc:
            raise AgentTransportError("agent answered with invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise AgentTransportError("agent answered with an unexpected JSON shape")
        return decoded

    async def aclose(self) -> None:
        await self._redis.aclose()
