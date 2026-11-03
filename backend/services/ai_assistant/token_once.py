"""Makes a signed confirmation usable once (doc/AI_TOOL_CHAIN.md §16).

The token is a signed claim, not a one-time secret: it can be presented many times inside its
lifetime. Its random id is recorded in Redis with ``SET NX``, and the store **fails closed**: when
Redis cannot record the id the start is refused (``ConfirmationStoreUnavailableError``). There is
deliberately no in-process fallback; a per-process window would let a replay, or a second worker,
start a second run of a workflow that may change devices.

Three steps around a start:

* ``claim`` before the start takes the id for a short in-flight period (a double click is refused);
* ``confirm`` after the run exists and was dispatched keeps the id for the rest of the token's life;
* ``release`` after a refusal or a failed dispatch frees it, so the same card can try again.
"""

from __future__ import annotations

import logging
from typing import Any

import redis

from core.config import settings
from services.ai_assistant.workflow_run_token import TOKEN_TTL_SECONDS

logger = logging.getLogger(__name__)

_KEY_PREFIX = "manus-ai-workflow-token:"
# How long a start may take before the claim lapses on its own (a crashed worker frees the id).
_IN_FLIGHT_SECONDS = 60
# A little longer than the token lives, so the record outlasts the token.
_USED_SECONDS = TOKEN_TTL_SECONDS + 60

_client: Any = None


class ConfirmationStoreUnavailableError(Exception):
    """Redis could not record the confirmation, so nothing may be started."""


def _redis() -> Any:
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
    return _client


def _key(token_id: str) -> str:
    return f"{_KEY_PREFIX}{token_id}"


def claim(token_id: str) -> bool:
    """True the first time ``token_id`` is seen (or after ``release``), False while it is held."""
    try:
        return bool(_redis().set(_key(token_id), "pending", nx=True, ex=_IN_FLIGHT_SECONDS))
    except redis.RedisError as exc:
        logger.error("AI confirmation store unavailable; refusing the start")
        raise ConfirmationStoreUnavailableError from exc


def confirm(token_id: str) -> None:
    """Keep the id for the rest of the token's life. The run already exists, so a Redis error
    here is logged, not raised: the in-flight claim still blocks a replay for its short life."""
    try:
        _redis().set(_key(token_id), "used", ex=_USED_SECONDS)
    except redis.RedisError:
        logger.error("AI confirmation store unavailable while marking a token used", exc_info=True)


def release(token_id: str) -> None:
    """Free the id after a refusal or a failed dispatch so the card can be used again."""
    try:
        _redis().delete(_key(token_id))
    except redis.RedisError:
        logger.warning("Could not release an AI confirmation claim", exc_info=True)
