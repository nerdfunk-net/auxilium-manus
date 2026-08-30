"""Tests for services/git/shared_utils.py and services/git/env.py."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from core.domain_exceptions import NotFoundError, ValidationFailedError
from services.git.env import set_ssl_env
from services.git.shared_utils import get_git_repo_by_id


class GetGitRepoByIdTests(unittest.TestCase):
    def test_missing_repository_raises_not_found(self) -> None:
        repos = MagicMock()
        repos.get_repository.return_value = None
        with self.assertRaises(NotFoundError):
            get_git_repo_by_id(1, repos)

    def test_inactive_repository_raises_validation(self) -> None:
        repos = MagicMock()
        repos.get_repository.return_value = {"name": "r", "is_active": False}
        with self.assertRaises(ValidationFailedError):
            get_git_repo_by_id(1, repos)

    def test_active_repository_delegates_to_git_service(self) -> None:
        repos = MagicMock()
        repos.get_repository.return_value = {"name": "r", "is_active": True}
        sentinel = object()
        with patch("service_factory.build_git_service") as build:
            build.return_value.open_or_clone.return_value = sentinel
            self.assertIs(get_git_repo_by_id(1, repos), sentinel)

    def test_open_or_clone_failure_becomes_runtime_error(self) -> None:
        repos = MagicMock()
        repos.get_repository.return_value = {"name": "r", "is_active": True}
        with patch("service_factory.build_git_service") as build:
            build.return_value.open_or_clone.side_effect = OSError("disk full")
            with self.assertRaises(RuntimeError):
                get_git_repo_by_id(1, repos)


class SetSslEnvTests(unittest.TestCase):
    def setUp(self) -> None:
        for key in ("GIT_SSL_NO_VERIFY", "GIT_SSL_CA_INFO", "GIT_SSL_CERT"):
            os.environ.pop(key, None)
            self.addCleanup(os.environ.pop, key, None)

    def test_verify_ssl_true_is_noop(self) -> None:
        with set_ssl_env({"verify_ssl": True, "url": "https://h/r.git"}):
            self.assertNotIn("GIT_SSL_NO_VERIFY", os.environ)

    def test_verify_ssl_false_sets_and_restores(self) -> None:
        with set_ssl_env({"verify_ssl": False, "url": "https://host/r.git"}):
            self.assertEqual(os.environ["GIT_SSL_NO_VERIFY"], "1")
        self.assertNotIn("GIT_SSL_NO_VERIFY", os.environ)

    def test_custom_ca_and_cert_applied(self) -> None:
        repo = {"verify_ssl": True, "ssl_ca_info": "/ca.pem", "ssl_cert": "/c.pem"}
        with set_ssl_env(repo):
            self.assertEqual(os.environ["GIT_SSL_CA_INFO"], "/ca.pem")
            self.assertEqual(os.environ["GIT_SSL_CERT"], "/c.pem")
        self.assertNotIn("GIT_SSL_CA_INFO", os.environ)

    def test_preexisting_value_is_restored(self) -> None:
        os.environ["GIT_SSL_NO_VERIFY"] = "keep"
        with set_ssl_env({"verify_ssl": False, "url": "https://host/r.git"}):
            self.assertEqual(os.environ["GIT_SSL_NO_VERIFY"], "1")
        self.assertEqual(os.environ["GIT_SSL_NO_VERIFY"], "keep")


if __name__ == "__main__":
    unittest.main()
