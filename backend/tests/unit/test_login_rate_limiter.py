"""Tests for the Redis-backed login rate limiter.

See doc/analysis/FABLE_BACKEND_20260912.md §4.2 (T1).
"""

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
        self.limiter._redis.eval.return_value = 1

        self.limiter.check("1.2.3.4:alice")  # must not raise
        # Count + record is ONE atomic Redis call (no ZCARD/ZADD race between requests).
        self.limiter._redis.eval.assert_called_once()
        self.limiter._redis.pipeline.assert_not_called()

    def test_blocks_once_the_window_is_full(self) -> None:
        self.limiter._redis.eval.return_value = 0

        with self.assertRaises(RateLimitExceededError):
            self.limiter.check("1.2.3.4:alice")

    def test_clear_removes_the_redis_key(self) -> None:
        self.limiter.clear("1.2.3.4:alice")

        self.limiter._redis.delete.assert_called_once_with("manus-login-rl:1.2.3.4:alice")

    def test_falls_back_to_in_process_limiter_when_redis_is_unreachable(self) -> None:
        self.limiter._redis.eval.side_effect = redis.ConnectionError("down")

        for _ in range(LOGIN_RATE_LIMIT_ATTEMPTS):
            self.limiter.check("1.2.3.4:bob")

        with self.assertRaises(RateLimitExceededError):
            self.limiter.check("1.2.3.4:bob")

    def test_assert_allowed_does_not_record(self) -> None:
        self.limiter._redis.pipeline.return_value.execute.return_value = [0, 0]

        self.limiter.assert_allowed("1.2.3.4:alice")

        self.limiter._redis.pipeline.assert_called_once()

    def test_record_adds_one_attempt(self) -> None:
        self.limiter._redis.pipeline.return_value.execute.return_value = [1, True]

        self.limiter.record("1.2.3.4:alice")

        self.limiter._redis.pipeline.assert_called_once()

    def test_custom_attempts_and_window_are_honoured(self) -> None:
        limiter = LoginRateLimiter(
            redis_url="redis://localhost:6379/0", attempts=2, window_seconds=5
        )
        limiter._redis = MagicMock()
        limiter._redis.pipeline.return_value.execute.side_effect = [
            [1, True],
            [1, True],
        ]

        limiter.record("1.2.3.4:alice")
        limiter.record("1.2.3.4:alice")

        expire_calls = [
            call
            for call in limiter._redis.pipeline.return_value.expire.call_args_list
        ]
        self.assertTrue(all(call.args[1] == 5 for call in expire_calls))

        limiter._redis.pipeline.return_value.execute.side_effect = [[0, 2]]
        with self.assertRaises(RateLimitExceededError):
            limiter.assert_allowed("1.2.3.4:alice")


class LoginRateLimiterFailClosedTests(unittest.TestCase):
    def setUp(self) -> None:
        self.limiter = LoginRateLimiter(
            redis_url="redis://localhost:6379/0", fail_closed=True
        )
        self.limiter._redis = MagicMock()

    def test_raises_immediately_when_redis_unreachable(self) -> None:
        self.limiter._redis.eval.side_effect = redis.ConnectionError("down")

        with self.assertRaises(RateLimitExceededError):
            self.limiter.check("1.2.3.4:carol")


class LoginRateLimiterConcurrencyTests(unittest.TestCase):
    def test_parallel_burst_never_exceeds_budget_in_process(self) -> None:
        import threading

        limiter = LoginRateLimiter(
            redis_url="redis://127.0.0.1:1/0", attempts=10, window_seconds=60
        )
        limiter._redis = MagicMock()
        limiter._redis.eval.side_effect = redis.ConnectionError("down")
        allowed: list[int] = []
        barrier = threading.Barrier(50)

        def hit() -> None:
            barrier.wait()
            try:
                limiter.check("burst")
                allowed.append(1)
            except RateLimitExceededError:
                pass

        threads = [threading.Thread(target=hit) for _ in range(50)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(allowed), 10)


if __name__ == "__main__":
    unittest.main()
