"""Tests for services/git/shared_utils.py and services/git/env.py."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from core.domain_exceptions import NotFoundError, ValidationFailedError
from services.git.env import build_git_env_overrides, merge_git_environ
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


class BuildGitEnvOverridesTests(unittest.TestCase):
    """S7: env overrides are built per-call and never touch os.environ."""

    def setUp(self) -> None:
        for key in ("GIT_SSL_NO_VERIFY", "GIT_SSL_CA_INFO", "GIT_SSL_CERT", "GIT_SSH_COMMAND"):
            os.environ.pop(key, None)
            self.addCleanup(os.environ.pop, key, None)

    def test_verify_ssl_true_omits_no_verify(self) -> None:
        overrides = build_git_env_overrides({"verify_ssl": True, "url": "https://h/r.git"})
        self.assertNotIn("GIT_SSL_NO_VERIFY", overrides)
        self.assertNotIn("GIT_SSL_NO_VERIFY", os.environ)

    def test_verify_ssl_false_sets_no_verify_without_touching_environ(self) -> None:
        overrides = build_git_env_overrides({"verify_ssl": False, "url": "https://host/r.git"})
        self.assertEqual(overrides["GIT_SSL_NO_VERIFY"], "1")
        self.assertNotIn("GIT_SSL_NO_VERIFY", os.environ)

    def test_custom_ca_and_cert_applied(self) -> None:
        overrides = build_git_env_overrides(
            {"verify_ssl": True, "ssl_ca_info": "/ca.pem", "ssl_cert": "/c.pem"}
        )
        self.assertEqual(overrides["GIT_SSL_CA_INFO"], "/ca.pem")
        self.assertEqual(overrides["GIT_SSL_CERT"], "/c.pem")
        self.assertNotIn("GIT_SSL_CA_INFO", os.environ)

    def test_ssh_key_path_adds_git_ssh_command(self) -> None:
        overrides = build_git_env_overrides(
            {"verify_ssl": True, "url": "ssh://git@h/r.git"},
            ssh_key_path="/keys/id_ed25519",
        )
        self.assertIn("GIT_SSH_COMMAND", overrides)
        self.assertIn("/keys/id_ed25519", overrides["GIT_SSH_COMMAND"])
        self.assertNotIn("GIT_SSH_COMMAND", os.environ)

    def test_no_ssh_key_path_omits_git_ssh_command(self) -> None:
        overrides = build_git_env_overrides({"verify_ssl": True, "url": "https://h/r.git"})
        self.assertNotIn("GIT_SSH_COMMAND", overrides)


class MergeGitEnvironTests(unittest.TestCase):
    def setUp(self) -> None:
        for key in ("GIT_SSL_NO_VERIFY", "GIT_SSL_CA_INFO", "GIT_SSL_CERT", "GIT_SSH_COMMAND"):
            os.environ.pop(key, None)
            self.addCleanup(os.environ.pop, key, None)

    def test_clears_inherited_git_pollution(self) -> None:
        os.environ["GIT_SSL_NO_VERIFY"] = "1"
        merged = merge_git_environ(build_git_env_overrides({"verify_ssl": True}))
        self.assertNotIn("GIT_SSL_NO_VERIFY", merged)

    def test_applies_overrides_on_top_of_environ_copy(self) -> None:
        os.environ["SOME_UNRELATED_VAR"] = "keep-me"
        merged = merge_git_environ({"GIT_SSL_NO_VERIFY": "1"})
        self.assertEqual(merged["GIT_SSL_NO_VERIFY"], "1")
        self.assertEqual(merged["SOME_UNRELATED_VAR"], "keep-me")
        self.addCleanup(os.environ.pop, "SOME_UNRELATED_VAR", None)

    def test_does_not_mutate_os_environ(self) -> None:
        merge_git_environ({"GIT_SSL_NO_VERIFY": "1", "GIT_SSH_COMMAND": "ssh -i x"})
        self.assertNotIn("GIT_SSL_NO_VERIFY", os.environ)
        self.assertNotIn("GIT_SSH_COMMAND", os.environ)


if __name__ == "__main__":
    unittest.main()
