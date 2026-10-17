"""Tests for the per-repository advisory git lock (services.git.repo_lock).

Redis is faked by an in-memory cache service; nothing here touches a real Redis instance.
`time.sleep` is patched out wherever a test exercises the poll/timeout path.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.git import repo_lock
from services.git.failure import GitOperationError
from services.git.repo_lock import (
    acquire_git_repo_lock,
    git_repo_lock,
    release_git_repo_lock,
)


class FakeCache:
    """In-memory stand-in for the lock-related RedisCacheService methods."""

    def __init__(self) -> None:
        self.data: dict[str, object] = {}

    def set_if_absent(self, key, data, ttl_seconds, *, raise_on_error=False) -> bool:
        if key in self.data:
            return False
        self.data[key] = data
        return True

    def delete_if_equals(self, key, data) -> bool:
        if self.data.get(key) == data:
            del self.data[key]
            return True
        return False

    def expire_if_equals(self, key, data, ttl_seconds) -> bool:
        return self.data.get(key) == data

    def expire(self, key) -> None:
        self.data.pop(key, None)


def _patch_cache(cache):
    return patch("service_factory.build_cache_service", return_value=cache)


class AcquireGitRepoLockTests(unittest.TestCase):
    def test_lease_holds_nothing_when_cache_unavailable(self) -> None:
        with _patch_cache(None):
            lease = acquire_git_repo_lock(7)
        self.assertIsNone(lease.value)
        lease.ensure_held()
        release_git_repo_lock(lease)  # must not raise

    def test_sets_key_with_an_owner_token_on_first_try(self) -> None:
        cache = FakeCache()
        with _patch_cache(cache):
            lease = acquire_git_repo_lock(7)
            self.assertEqual(cache.data["git-repo-lock:7"], lease.value)
            self.assertIn("token", lease.value)
            release_git_repo_lock(lease)
        self.assertNotIn("git-repo-lock:7", cache.data)

    def test_polls_until_the_holder_releases(self) -> None:
        cache = MagicMock()
        cache.set_if_absent.side_effect = [False, False, True]
        with (
            _patch_cache(cache),
            patch("services.git.repo_lock.time.sleep") as sleep_mock,
            patch("services.git.repo_lock.threading.Thread"),
        ):
            lease = acquire_git_repo_lock(7)
        self.assertIsNotNone(lease.value)
        self.assertEqual(cache.set_if_absent.call_count, 3)
        self.assertEqual(sleep_mock.call_count, 2)

    def test_redis_error_skips_lock_without_spinning(self) -> None:
        cache = MagicMock()
        cache.set_if_absent.side_effect = ConnectionError("redis down")
        with _patch_cache(cache), patch("services.git.repo_lock.time.sleep") as sleep_mock:
            lease = acquire_git_repo_lock(7)
        self.assertIsNone(lease.value)
        cache.set_if_absent.assert_called_once()
        sleep_mock.assert_not_called()

    def test_raises_repo_locked_on_timeout(self) -> None:
        cache = MagicMock()
        cache.set_if_absent.return_value = False
        with (
            _patch_cache(cache),
            patch("services.git.repo_lock.time.sleep"),
            patch("services.git.repo_lock.time.monotonic", side_effect=[0.0, 1000.0]),
        ):
            with self.assertRaises(GitOperationError) as ctx:
                acquire_git_repo_lock(7)
        self.assertEqual(ctx.exception.failure.kind, "repo_locked")


class LeaseOwnershipTests(unittest.TestCase):
    def test_release_does_not_delete_a_lock_taken_over_after_expiry(self) -> None:
        cache = FakeCache()
        with _patch_cache(cache), patch("services.git.repo_lock.threading.Thread"):
            a = acquire_git_repo_lock(7)
            cache.expire("git-repo-lock:7")  # A's TTL ran out
            b = acquire_git_repo_lock(7)
            a.release()  # A is late
            self.assertEqual(cache.data["git-repo-lock:7"], b.value)
            b.release()
        self.assertNotIn("git-repo-lock:7", cache.data)

    def test_lease_is_renewed_while_held(self) -> None:
        cache = FakeCache()
        with _patch_cache(cache), patch("services.git.repo_lock.threading.Thread"):
            lease = acquire_git_repo_lock(7)
        waits = iter([False, True])  # one renewal tick, then stop
        lease._stop = MagicMock()
        lease._stop.wait.side_effect = lambda _t: next(waits)
        with _patch_cache(cache):
            repo_lock._renew(lease)
        self.assertFalse(lease.lost)

    def test_lost_lease_is_reported_to_the_holder(self) -> None:
        cache = FakeCache()
        with _patch_cache(cache), patch("services.git.repo_lock.threading.Thread"):
            lease = acquire_git_repo_lock(7)
        cache.expire("git-repo-lock:7")
        lease._stop = MagicMock()
        lease._stop.wait.return_value = False
        with _patch_cache(cache):
            repo_lock._renew(lease)
        self.assertTrue(lease.lost)
        with self.assertRaises(GitOperationError) as ctx:
            lease.ensure_held()
        self.assertEqual(ctx.exception.failure.kind, "repo_locked")


class GitRepoLockContextManagerTests(unittest.TestCase):
    def test_acquires_then_releases_around_the_block(self) -> None:
        cache = FakeCache()
        calls: list[str] = []
        with _patch_cache(cache):
            with git_repo_lock(7) as lease:
                calls.append("inside")
                self.assertIn("git-repo-lock:7", cache.data)
                self.assertIsNotNone(lease.value)
        self.assertNotIn("git-repo-lock:7", cache.data)
        self.assertEqual(calls, ["inside"])

    def test_releases_even_when_the_block_raises(self) -> None:
        cache = FakeCache()
        with _patch_cache(cache):
            with self.assertRaises(RuntimeError):
                with git_repo_lock(7):
                    raise RuntimeError("boom")
        self.assertNotIn("git-repo-lock:7", cache.data)

    def test_does_not_fail_when_it_never_acquired(self) -> None:
        with _patch_cache(None):
            with git_repo_lock(7):
                pass


class CurrentLeaseTests(unittest.TestCase):
    def test_lost_lease_fails_the_next_checked_call_inside_the_block(self) -> None:
        cache = FakeCache()
        with _patch_cache(cache), patch("services.git.repo_lock.threading.Thread"):
            with git_repo_lock(7) as lease:
                repo_lock.ensure_current_lease_held()  # still held: fine
                lease.lost = True
                with self.assertRaises(GitOperationError) as ctx:
                    repo_lock.ensure_current_lease_held()
        self.assertEqual(ctx.exception.failure.kind, "repo_locked")

    def test_no_check_outside_a_lock_block(self) -> None:
        repo_lock.ensure_current_lease_held()

    def test_lease_is_cleared_after_the_block(self) -> None:
        cache = FakeCache()
        with _patch_cache(cache), patch("services.git.repo_lock.threading.Thread"):
            with git_repo_lock(7) as lease:
                lease.lost = True
        repo_lock.ensure_current_lease_held()


if __name__ == "__main__":
    unittest.main()


class RequiredLockTests(unittest.TestCase):
    """O2-05: where Redis is part of the deployment, no lock must mean no git write."""

    def setUp(self) -> None:
        patcher = patch("services.git.repo_lock._lock_required", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_cache_refuses_instead_of_proceeding_unlocked(self) -> None:
        with _patch_cache(None), self.assertRaises(GitOperationError) as ctx:
            acquire_git_repo_lock(7)
        failure = ctx.exception.failure
        self.assertEqual((failure.phase, failure.kind), ("git", "repo_locked"))
        self.assertTrue(failure.retryable)
        self.assertEqual(failure.hint, "retry_later")

    def test_a_redis_error_while_acquiring_refuses(self) -> None:
        cache = MagicMock()
        cache.set_if_absent.side_effect = ConnectionError("redis down")
        with (
            _patch_cache(cache),
            patch("services.git.repo_lock.time.sleep") as sleep_mock,
            self.assertRaises(GitOperationError) as ctx,
        ):
            acquire_git_repo_lock(7)
        self.assertEqual(ctx.exception.failure.kind, "repo_locked")
        sleep_mock.assert_not_called()

    def test_the_context_manager_does_not_run_its_block_without_a_lock(self) -> None:
        ran = []
        with _patch_cache(None), self.assertRaises(GitOperationError):
            with git_repo_lock(7):
                ran.append(True)
        self.assertEqual(ran, [])

    def test_a_working_cache_still_locks_normally(self) -> None:
        with _patch_cache(FakeCache()):
            lease = acquire_git_repo_lock(7)
            self.assertIsNotNone(lease.value)
            release_git_repo_lock(lease)

    def test_the_error_message_names_the_cause_without_internals(self) -> None:
        with _patch_cache(None), self.assertRaises(GitOperationError) as ctx:
            acquire_git_repo_lock(7)
        self.assertIn("lock", str(ctx.exception).lower())
        self.assertIn("redis", str(ctx.exception).lower())
