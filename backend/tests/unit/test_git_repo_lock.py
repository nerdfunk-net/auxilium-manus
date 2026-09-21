"""Tests for the per-repository advisory git lock (services.git.repo_lock).

Redis is faked via a MagicMock cache service; nothing here touches a real
Redis instance. `time.sleep` is patched out wherever a test exercises the
poll/timeout path so it runs instantly.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.git.repo_lock import (
    acquire_git_repo_lock,
    git_repo_lock,
    release_git_repo_lock,
)


class AcquireGitRepoLockTests(unittest.TestCase):
    def test_returns_false_when_cache_unavailable(self) -> None:
        with patch("service_factory.build_cache_service", return_value=None):
            self.assertFalse(acquire_git_repo_lock(7))

    def test_returns_true_and_sets_key_on_first_try(self) -> None:
        cache = MagicMock()
        cache.set_if_absent.return_value = True
        with patch("service_factory.build_cache_service", return_value=cache):
            self.assertTrue(acquire_git_repo_lock(7))
        cache.set_if_absent.assert_called_once_with("git-repo-lock:7", {"held": True}, 120)

    def test_polls_until_the_holder_releases(self) -> None:
        cache = MagicMock()
        cache.set_if_absent.side_effect = [False, False, True]
        with (
            patch("service_factory.build_cache_service", return_value=cache),
            patch("services.git.repo_lock.time.sleep") as sleep_mock,
        ):
            self.assertTrue(acquire_git_repo_lock(7))
        self.assertEqual(cache.set_if_absent.call_count, 3)
        self.assertEqual(sleep_mock.call_count, 2)

    def test_fails_soft_and_returns_false_on_timeout(self) -> None:
        cache = MagicMock()
        cache.set_if_absent.return_value = False
        # Make the deadline appear already passed on the second monotonic()
        # call (the first sets the deadline, the loop check follows).
        with (
            patch("service_factory.build_cache_service", return_value=cache),
            patch("services.git.repo_lock.time.sleep"),
            patch(
                "services.git.repo_lock.time.monotonic",
                side_effect=[0.0, 1000.0],
            ),
        ):
            self.assertFalse(acquire_git_repo_lock(7))


class ReleaseGitRepoLockTests(unittest.TestCase):
    def test_noop_when_not_acquired(self) -> None:
        with patch("service_factory.build_cache_service") as build_mock:
            release_git_repo_lock(7, False)
        build_mock.assert_not_called()

    def test_deletes_key_when_acquired(self) -> None:
        cache = MagicMock()
        with patch("service_factory.build_cache_service", return_value=cache):
            release_git_repo_lock(7, True)
        cache.delete.assert_called_once_with("git-repo-lock:7")

    def test_noop_when_acquired_but_cache_now_unavailable(self) -> None:
        with patch("service_factory.build_cache_service", return_value=None):
            release_git_repo_lock(7, True)  # must not raise


class GitRepoLockContextManagerTests(unittest.TestCase):
    def test_acquires_then_releases_around_the_block(self) -> None:
        cache = MagicMock()
        cache.set_if_absent.return_value = True
        calls: list[str] = []
        with patch("service_factory.build_cache_service", return_value=cache):
            with git_repo_lock(7):
                calls.append("inside")
        cache.set_if_absent.assert_called_once_with("git-repo-lock:7", {"held": True}, 120)
        cache.delete.assert_called_once_with("git-repo-lock:7")
        self.assertEqual(calls, ["inside"])

    def test_releases_even_when_the_block_raises(self) -> None:
        cache = MagicMock()
        cache.set_if_absent.return_value = True
        with patch("service_factory.build_cache_service", return_value=cache):
            with self.assertRaises(RuntimeError):
                with git_repo_lock(7):
                    raise RuntimeError("boom")
        cache.delete.assert_called_once_with("git-repo-lock:7")

    def test_does_not_release_when_it_never_acquired(self) -> None:
        with patch("service_factory.build_cache_service", return_value=None):
            with git_repo_lock(7):
                pass
        # No cache at all -- nothing to assert on delete, just must not raise.


if __name__ == "__main__":
    unittest.main()
