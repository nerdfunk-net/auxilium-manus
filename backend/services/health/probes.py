"""Dependency probes for GET /health/ready (each blocks, so ``check_readiness`` threads them)."""

from __future__ import annotations

import redis

# Shorter than the readiness deadline, so the socket gives up on its own and the thread is freed.
REDIS_PROBE_SOCKET_TIMEOUT_SECONDS = 2.0


def ping_redis(url: str) -> None:
    """Raise if Redis does not answer. Uses its own short-lived client: the shared cache client is
    created lazily, retried on every call while Redis is down, and has no short timeout."""
    client = redis.from_url(
        url,
        socket_connect_timeout=REDIS_PROBE_SOCKET_TIMEOUT_SECONDS,
        socket_timeout=REDIS_PROBE_SOCKET_TIMEOUT_SECONDS,
    )
    try:
        client.ping()
    finally:
        client.close()
