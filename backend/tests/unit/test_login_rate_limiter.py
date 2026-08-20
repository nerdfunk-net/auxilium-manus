"""Tests for the Redis-backed login rate limiter — see doc/FABLE-ANALYSIS.md §4.6."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import redis

from services.auth.login_rate_limiter import (
    LOGIN_RATE_LIMIT_ATTEMPTS,
    LoginRateLimiter,
    RateLimitExceededError,
)


class LoginRateLimiterRedisTests(unittest.TestCase):
    def setUp(self) -> None:
        self.limiter = LoginRateLimiter(redis_url="redis://localhost:6379/0")
        self.limiter._redis = MagicMock()

    def test_allows_attempts_under_the_limit(self) -> None:
        self.limiter._redis.pipeline.return_value.execute.side_effect = [
            [0, LOGIN_RATE_LIMIT_ATTEMPTS - 1],
            [1, True],
        ]

        self.limiter.check("1.2.3.4:alice")  # must not raise

    def test_blocks_once_the_window_is_full(self) -> None:
        self.limiter._redis.pipeline.return_value.execute.side_effect = [
            [0, LOGIN_RATE_LIMIT_ATTEMPTS],
        ]

        with self.assertRaises(RateLimitExceededError):
            self.limiter.check("1.2.3.4:alice")

    def test_clear_removes_the_redis_key(self) -> None:
        self.limiter.clear("1.2.3.4:alice")

        self.limiter._redis.delete.assert_called_once_with("manus-login-rl:1.2.3.4:alice")

    def test_falls_back_to_in_process_limiter_when_redis_is_unreachable(self) -> None:
        self.limiter._redis.pipeline.side_effect = redis.ConnectionError("down")

        for _ in range(LOGIN_RATE_LIMIT_ATTEMPTS):
            self.limiter.check("1.2.3.4:bob")

        with self.assertRaises(RateLimitExceededError):
            self.limiter.check("1.2.3.4:bob")


class LoginRateLimiterFailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.limiter = LoginRateLimiter(
            redis_url="redis://localhost:6379/0", fail_closed=True
        )
        self.limiter._redis = MagicMock()

    def test_raises_immediately_when_redis_unreachable(self) -> None:
        self.limiter._redis.pipeline.side_effect = redis.ConnectionError("down")

        with self.assertRaises(RateLimitExceededError):
            self.limiter.check("1.2.3.4:carol")


if __name__ == "__main__":
    unittest.main()
