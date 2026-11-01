"""Handle store: big tool results live here, the prompt only gets a preview and a handle.

Decision D6 (doc/AI_TOOL_CHAIN.md §19): short-lived, per user, not in the database. Redis holds
each result under ``<prefix>:<user_id>:<handle>`` with an expiry, so

* a handle only resolves for the user who created it (the user id is part of the key; another
  user's handle simply does not exist, indistinguishable from an expired one),
* no migration and no retention job are needed,
* an expired handle returns ``None`` and the caller tells the model to fetch again.

Handles are random (48 bits) and checked against ``HANDLE_PATTERN`` before they touch a key, so
model-supplied text can never shape a Redis key. Conversation scoping (§6.1 says "same
conversation") is not done yet: the tool context carries no conversation id. Scope is the user.

Redis is the only production backend. When it is unreachable ``put`` and ``get`` raise
``ResultStoreUnavailableError``; callers degrade (preview without handle) and never fall back to
per-process memory, which would break with several workers. ``InMemoryResultBackend`` exists for
tests and single-process development only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any, Protocol

import redis

from services.ai_assistant.data_sharing import DataClass

logger = logging.getLogger(__name__)

HANDLE_PATTERN = re.compile(r"^res_[0-9a-f]{12}$")
# Hours, not days: these are intermediate results (D6). An expired handle means "fetch again".
DEFAULT_TTL_SECONDS = 4 * 3600
# Per handle, serialised. Bigger results are cut by the producing tool before they are stored.
MAX_STORED_BYTES = 2_000_000
DEFAULT_KEY_PREFIX = "manus-ai-result"


class ResultStoreUnavailableError(Exception):
    """The backing store could not be reached; the result was neither saved nor read."""


@dataclass(frozen=True)
class StoredResult:
    """One stored result: tabular ``rows`` or plain ``text`` (exactly one of them).

    ``data_class`` is the class the data was read under. It is checked again on every read, so a
    user who switches the opt-in off stops seeing old handles' content straight away.
    """

    kind: str
    data_class: DataClass
    rows: list[dict[str, Any]] | None = None
    text: str | None = None
    # True when ``rows`` is only a prefix of the full answer (cut at the source's preview cap or
    # to fit the store). A comparison of two stored tables must say so.
    partial: bool = False

    def __post_init__(self) -> None:
        if (self.rows is None) == (self.text is None):
            raise ValueError("a stored result needs exactly one of rows or text")


class ResultBackend(Protocol):
    def set(self, key: str, value: str, ttl_seconds: int) -> None: ...

    def get(self, key: str) -> str | None: ...


class RedisResultBackend:
    def __init__(self, client: Any) -> None:
        # decode_responses=True is expected: replies are str.
        self._client = client

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        try:
            self._client.set(key, value, ex=ttl_seconds)
        except redis.RedisError as exc:
            raise ResultStoreUnavailableError("result store unavailable") from exc

    def get(self, key: str) -> str | None:
        try:
            value = self._client.get(key)
        except redis.RedisError as exc:
            raise ResultStoreUnavailableError("result store unavailable") from exc
        return value if isinstance(value, str) else None


class InMemoryResultBackend:
    """Tests and single-process development. Honours the TTL."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[float, str]] = {}

    def set(self, key: str, value: str, ttl_seconds: int) -> None:
        self._data[key] = (time.monotonic() + ttl_seconds, value)

    def get(self, key: str) -> str | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        if entry[0] <= time.monotonic():
            del self._data[key]
            return None
        return entry[1]


def _json_default(value: Any) -> Any:
    if isinstance(value, (set, frozenset)):
        return sorted(value, key=str)
    return str(value)


class ResultStore:
    def __init__(
        self,
        backend: ResultBackend,
        *,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        key_prefix: str = DEFAULT_KEY_PREFIX,
    ) -> None:
        self._backend = backend
        self._ttl = ttl_seconds
        self._prefix = key_prefix

    def _key(self, user_id: int, handle: str) -> str:
        return f"{self._prefix}:{user_id}:{handle}"

    async def put(self, user_id: int, result: StoredResult) -> str:
        """Store ``result`` for ``user_id`` and return its handle.

        Raises ``ValueError`` when the serialised result exceeds ``MAX_STORED_BYTES`` and
        ``ResultStoreUnavailableError`` when the backend cannot be reached.
        """
        payload = json.dumps(
            {
                "kind": result.kind,
                "data_class": result.data_class.value,
                "rows": result.rows,
                "text": result.text,
                "partial": result.partial,
            },
            default=_json_default,
            ensure_ascii=False,
        )
        if len(payload.encode("utf-8")) > MAX_STORED_BYTES:
            raise ValueError("result is too large to store")
        handle = f"res_{secrets.token_hex(6)}"
        await asyncio.to_thread(self._backend.set, self._key(user_id, handle), payload, self._ttl)
        return handle

    async def get(self, user_id: int, handle: str) -> StoredResult | None:
        """The stored result, or ``None`` when the handle is malformed, unknown, expired, belongs
        to another user or is damaged (all deliberately the same answer)."""
        if not HANDLE_PATTERN.fullmatch(handle):
            return None
        raw = await asyncio.to_thread(self._backend.get, self._key(user_id, handle))
        if raw is None:
            return None
        try:
            data = json.loads(raw)
            return StoredResult(
                kind=data["kind"],
                data_class=DataClass(data["data_class"]),
                rows=data["rows"],
                text=data["text"],
                partial=bool(data.get("partial", False)),
            )
        except ValueError, KeyError, TypeError:
            logger.warning("Dropping a damaged AI result entry")
            return None
