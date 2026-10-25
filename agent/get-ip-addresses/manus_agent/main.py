"""Run the agent: ``python -m manus_agent`` (configuration comes from the environment)."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from collections.abc import Callable, Mapping
from typing import Any

import redis.asyncio as aioredis
from aiohttp import web

from manus_agent.config import AgentConfig, ConfigError, load_config
from manus_agent.core import AgentCore
from manus_agent.data_source import DataSourceError, load_index
from manus_agent.http_server import create_app
from manus_agent.ip_index import set_index
from manus_agent.redis_worker import RedisWorker
from manus_agent.registry import HandlerRegistry, builtin_registry

logger = logging.getLogger("manus_agent")


def _connect(url: str) -> aioredis.Redis:
    return aioredis.from_url(url, decode_responses=True)


def build_registry(config: AgentConfig) -> HandlerRegistry:
    registry = builtin_registry()
    registry.load_directory(config.handlers_dir)
    return registry


async def serve(
    config: AgentConfig,
    registry: HandlerRegistry,
    stop: asyncio.Event,
    *,
    redis_factory: Callable[[str], aioredis.Redis] = _connect,
) -> None:
    """Run the enabled transports until *stop* is set, then shut them down in order."""
    core = AgentCore(config, registry)
    runner: web.AppRunner | None = None
    worker_task: asyncio.Task[None] | None = None
    client: aioredis.Redis | None = None
    stop_task = asyncio.create_task(stop.wait())

    try:
        if config.http_port is not None:
            runner = web.AppRunner(create_app(core, config))
            await runner.setup()
            await web.TCPSite(runner, config.http_host, config.http_port).start()
            logger.info("http transport listening on %s:%s", config.http_host, config.http_port)
        if config.redis_url is not None:
            client = redis_factory(config.redis_url)
            worker = RedisWorker(core, config, registry, client)
            worker_task = asyncio.create_task(worker.run(stop))

        # A transport that dies must take the agent down (so a supervisor restarts it) instead
        # of leaving the other transport serving while this one is silently gone.
        watched: set[asyncio.Task[Any]] = {stop_task}
        if worker_task is not None:
            watched.add(worker_task)
        await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
        if worker_task is not None and worker_task.done() and not stop.is_set():
            worker_task.result()  # re-raises the worker's own error
            raise RuntimeError("the redis worker stopped unexpectedly")
    finally:
        stop.set()
        stop_task.cancel()
        if worker_task is not None:
            # Whatever the worker died of has already been raised above; clean up regardless.
            await asyncio.gather(worker_task, return_exceptions=True)
        if runner is not None:
            await runner.cleanup()
        if client is not None:
            await client.aclose()
        core.close()


async def _run(config: AgentConfig, registry: HandlerRegistry) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    await serve(config, registry, stop)


def main(env: Mapping[str, str] | None = None) -> int:
    try:
        config = load_config(os.environ if env is None else env)
    except ConfigError as exc:
        print(f"manus-agent: configuration error: {exc}", file=sys.stderr)
        return 2
    logging.basicConfig(
        level=getattr(logging, config.loglevel, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        registry = build_registry(config)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"manus-agent: cannot load handlers: {exc}", file=sys.stderr)
        return 3
    try:
        # Pull the repository and cache its content before the first request can arrive. An
        # agent without data must not start (a supervisor restarts it and the log says why).
        set_index(load_index(os.environ if env is None else env))
    except DataSourceError as exc:
        print(f"manus-agent: cannot load the data: {exc}", file=sys.stderr)
        return 4
    logger.info(
        "agent %s v%s starting; transports: %s; handlers: %s",
        config.agent_id,
        config.version,
        ", ".join(
            name
            for name, enabled in (("http", config.http_port), ("redis", config.redis_url))
            if enabled
        ),
        ", ".join(registry.names()),
    )
    try:
        asyncio.run(_run(config, registry))
    except Exception:
        logger.exception("agent stopped because of an unexpected error")
        return 1
    return 0
