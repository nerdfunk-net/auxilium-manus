"""The process-wide ``ResultStore``, backed by the app's Redis (doc/AI_TOOL_CHAIN.md D6).

``redis.from_url`` does not connect, so creating the store never fails and never blocks; an
unreachable Redis shows up later as ``ResultStoreUnavailableError`` and the tools degrade to a
preview without a handle. The short socket timeouts keep a Redis outage from stalling a chat turn.
"""

from __future__ import annotations

import threading

import redis

from core.config import settings
from services.ai_assistant.results.store import RedisResultBackend, ResultStore

_SOCKET_TIMEOUT_SECONDS = 2.0

_lock = threading.Lock()
_store: ResultStore | None = None


def get_result_store() -> ResultStore:
    global _store
    if _store is None:
        with _lock:
            if _store is None:
                client = redis.from_url(
                    settings.redis_url,
                    decode_responses=True,
                    socket_timeout=_SOCKET_TIMEOUT_SECONDS,
                    socket_connect_timeout=_SOCKET_TIMEOUT_SECONDS,
                )
                _store = ResultStore(
                    RedisResultBackend(client), key_prefix=f"{settings.redis_key_prefix}:ai-result"
                )
    return _store
