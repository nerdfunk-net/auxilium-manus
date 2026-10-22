"""Redis transport: take requests from a list, answer on a per-command list, keep a heartbeat.

Keys, all under ``manus-agent:{agent_id}:`` (the agent's Redis user is limited to this prefix
and to the commands used here: BLPOP, RPUSH, HSET, EXPIRE, DEL, PING)::

    req            list  the app RPUSHes sealed requests, this worker BLPOPs them
    resp:{cmd}     list  this worker RPUSHes the sealed answer, the app BLPOPs it
    hb             hash  heartbeat (status, version, handlers, last_heartbeat), expires

The worker only pulls a request when it has capacity to run it, so surplus work stays in the
queue instead of piling up in memory, and a stopped agent leaves nothing half done.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from manus_agent.config import AgentConfig
from manus_agent.core import AgentCore, RequestRejected
from manus_agent.registry import HandlerRegistry

logger = logging.getLogger(__name__)

KEY_PREFIX = "manus-agent"
RESPONSE_KEY_TTL_SECONDS = 120


def request_key(agent_id: str) -> str:
    return f"{KEY_PREFIX}:{agent_id}:req"


def response_key(agent_id: str, command_id: str) -> str:
    return f"{KEY_PREFIX}:{agent_id}:resp:{command_id}"


def heartbeat_key(agent_id: str) -> str:
    return f"{KEY_PREFIX}:{agent_id}:hb"


class RedisWorker:
    def __init__(
        self,
        core: AgentCore,
        config: AgentConfig,
        registry: HandlerRegistry,
        client: aioredis.Redis,
        *,
        heartbeat_interval: float = 30.0,
        heartbeat_ttl: int = 90,
        poll_timeout: float = 1.0,
        retry_delay: float = 5.0,
        shutdown_grace: float = 10.0,
    ) -> None:
        self._core = core
        self._config = config
        self._registry = registry
        self._redis = client
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_ttl = heartbeat_ttl
        self._poll_timeout = poll_timeout
        self._retry_delay = retry_delay
        self._shutdown_grace = shutdown_grace
        self._inflight: set[asyncio.Task[None]] = set()

    async def run(self, stop: asyncio.Event) -> None:
        heartbeat = asyncio.create_task(self._heartbeat_loop(stop))
        try:
            await self._consume(stop)
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            await self._drain()
            await self._mark_offline()

    # -- consuming -----------------------------------------------------------------

    async def _consume(self, stop: asyncio.Event) -> None:
        gate = asyncio.Semaphore(self._config.max_concurrency)
        queue = request_key(self._config.agent_id)
        logger.info("redis worker listening on %s", queue)
        while not stop.is_set():
            try:
                await asyncio.wait_for(gate.acquire(), timeout=self._poll_timeout)
            except TimeoutError:  # noqa: S112 - no capacity yet; look at `stop` and wait again
                continue
            try:
                popped = await self._redis.blpop([queue], timeout=self._poll_timeout)  # type: ignore[misc]
            except (RedisError, OSError) as exc:
                gate.release()
                logger.warning("redis unavailable (%s); retrying", type(exc).__name__)
                await self._pause(stop, self._retry_delay)
                continue
            if popped is None:
                gate.release()
                continue
            task = asyncio.create_task(self._serve(popped[1], gate))
            self._inflight.add(task)
            task.add_done_callback(self._inflight.discard)

    async def _serve(self, raw: str, gate: asyncio.Semaphore) -> None:
        try:
            try:
                envelope: Any = json.loads(raw)
            except ValueError:
                logger.warning("dropped a request that is not JSON")
                return
            try:
                answer = await self._core.handle(envelope)
            except RequestRejected:
                return  # already logged; there is nobody entitled to an answer
            except Exception:
                logger.exception("unexpected error while handling a request")
                return
            key = response_key(self._config.agent_id, answer["command_id"])
            try:
                await self._redis.rpush(key, json.dumps(answer))  # type: ignore[misc]
                await self._redis.expire(key, RESPONSE_KEY_TTL_SECONDS)
            except (RedisError, OSError) as exc:
                logger.warning("could not deliver an answer (%s)", type(exc).__name__)
        finally:
            gate.release()

    # -- heartbeat -----------------------------------------------------------------

    async def _heartbeat_loop(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                await self._beat()
            except (RedisError, OSError) as exc:
                logger.debug("heartbeat failed (%s)", type(exc).__name__)
            await self._pause(stop, self._heartbeat_interval)

    async def _beat(self) -> None:
        key = heartbeat_key(self._config.agent_id)
        await self._redis.hset(  # type: ignore[misc]
            key,
            mapping={
                "status": "online",
                "agent_id": self._config.agent_id,
                "version": self._config.version,
                "handlers": ",".join(self._registry.names()),
                "last_heartbeat": int(time.time()),
            },
        )
        await self._redis.expire(key, self._heartbeat_ttl)

    async def _mark_offline(self) -> None:
        try:
            await self._redis.delete(heartbeat_key(self._config.agent_id))  # type: ignore[misc]
        except (RedisError, OSError):
            logger.debug("could not remove the heartbeat on shutdown")

    # -- helpers -------------------------------------------------------------------

    async def _drain(self) -> None:
        if not self._inflight:
            return
        _, pending = await asyncio.wait(set(self._inflight), timeout=self._shutdown_grace)
        for task in pending:
            task.cancel()

    @staticmethod
    async def _pause(stop: asyncio.Event, seconds: float) -> None:
        try:
            await asyncio.wait_for(stop.wait(), timeout=seconds)
        except TimeoutError:  # noqa: S110 - the interval elapsed; that is the normal wake-up
            pass
