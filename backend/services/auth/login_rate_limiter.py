"""Redis-backed login rate limiting, shared across worker processes.

Replaces the per-process ``defaultdict`` limiter that used to live in
``routers/auth.py`` — see doc/FABLE-ANALYSIS.md §4.6. Falls back to an
in-process sliding window when Redis is unreachable at check time, so a
transient Redis outage degrades rate-limit fidelity (per-worker instead of
global) rather than blocking login entirely, mirroring the fail-soft pattern
already used by ``service_factory.build_cache_service()``.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

import redis

logger = logging.getLogger(__name__)

LOGIN_RATE_LIMIT_ATTEMPTS = 5
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 60


class RateLimitExceededError(Exception):
    """Raised when a rate-limit key has exceeded its attempt budget."""


class LoginRateLimiter:
    """Sliding-window login-attempt limiter.

    Uses one Redis sorted set per key (member and score are both the attempt
    timestamp): entries older than the window are trimmed on every check via
    ``ZREMRANGEBYSCORE``, then ``ZCARD`` gives the current attempt count. This
    is the standard sliding-window-log pattern and keeps Redis memory bounded
    without a background sweep — ``EXPIRE`` on the key means an abandoned key
    (no further attempts) disappears on its own after the window elapses,
    unlike the previous in-process dict, which kept an empty deque forever
    once touched.
    """

    def __init__(self, redis_url: str, key_prefix: str = "manus-login-rl") -> None:
        # redis.from_url does not connect eagerly, so constructing this is
        # always safe even if Redis is down — failures only surface, and are
        # only handled, inside check()/clear().
        self._redis = redis.from_url(redis_url, decode_responses=True)
        self._prefix = key_prefix
        self._fallback_attempts: defaultdict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        """Raise RateLimitExceededError if key is over budget; else record this attempt."""
        try:
            self._check_redis(key)
        except redis.RedisError:
            logger.warning(
                "Login rate limiter: Redis unavailable, using in-process fallback for this check"
            )
            self._check_fallback(key)

    def clear(self, key: str) -> None:
        """Reset a key's attempt history (called after a successful login)."""
        try:
            self._redis.delete(self._redis_key(key))
        except redis.RedisError:
            pass
        self._fallback_attempts.pop(key, None)

    def _redis_key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    def _check_redis(self, key: str) -> None:
        redis_key = self._redis_key(key)
        now = time.time()
        window_start = now - LOGIN_RATE_LIMIT_WINDOW_SECONDS

        trim_and_count = self._redis.pipeline()
        trim_and_count.zremrangebyscore(redis_key, 0, window_start)
        trim_and_count.zcard(redis_key)
        _removed, attempt_count = trim_and_count.execute()

        if attempt_count >= LOGIN_RATE_LIMIT_ATTEMPTS:
            raise RateLimitExceededError(key)

        record_attempt = self._redis.pipeline()
        record_attempt.zadd(redis_key, {f"{now!r}": now})
        record_attempt.expire(redis_key, LOGIN_RATE_LIMIT_WINDOW_SECONDS)
        record_attempt.execute()

    def _check_fallback(self, key: str) -> None:
        now = time.monotonic()
        attempts = self._fallback_attempts[key]

        while attempts and now - attempts[0] > LOGIN_RATE_LIMIT_WINDOW_SECONDS:
            attempts.popleft()

        if len(attempts) >= LOGIN_RATE_LIMIT_ATTEMPTS:
            raise RateLimitExceededError(key)

        attempts.append(now)
