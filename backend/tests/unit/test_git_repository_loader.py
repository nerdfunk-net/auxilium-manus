"""Tests for the workflow-step git repository loader."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class GitRepositoryLoaderTests(unittest.TestCase):
    def test_loads_repository_dict_from_service(self) -> None:
        with (
            patch("workflow_steps.common.git_repository_loader.get_db_session") as session_factory,
            patch(
                "workflow_steps.common.git_repository_loader.GitRepositoryService"
            ) as service_cls,
        ):
            from workflow_steps.common.git_repository_loader import load_git_repository

            session_factory.return_value = MagicMock()
            service_cls.return_value.get_repository.return_value = {
                "id": 7,
                "name": "prod-configs",
                "url": "https://example.com/repo.git",
                "branch": "main",
                "auth_type": "token",
                "credential_name": "prod-configs-token",
                "path": None,
                "verify_ssl": True,
                "is_active": True,
            }

            repository = load_git_repository(7)

        self.assertEqual(repository["name"], "prod-configs")
        self.assertEqual(repository["url"], "https://example.com/repo.git")
        self.assertEqual(repository["credential_name"], "prod-configs-token")
        self.assertTrue(repository["verify_ssl"])

    def test_missing_repository_raises(self) -> None:
        with (
            patch("workflow_steps.common.git_repository_loader.get_db_session") as session_factory,
            patch(
                "workflow_steps.common.git_repository_loader.GitRepositoryService"
            ) as service_cls,
        ):
            from workflow_steps.common.git_repository_loader import load_git_repository

            session_factory.return_value = MagicMock()
            service_cls.return_value.get_repository.return_value = None

            with self.assertRaisesRegex(ValueError, "not found"):
                load_git_repository(99)

    def test_inactive_repository_raises(self) -> None:
        with (
            patch("workflow_steps.common.git_repository_loader.get_db_session") as session_factory,
            patch(
                "workflow_steps.common.git_repository_loader.GitRepositoryService"
            ) as service_cls,
        ):
            from workflow_steps.common.git_repository_loader import load_git_repository

            session_factory.return_value = MagicMock()
            service_cls.return_value.get_repository.return_value = {
                "id": 7,
                "name": "prod-configs",
                "url": "https://example.com/repo.git",
                "is_active": False,
            }

            with self.assertRaisesRegex(ValueError, "not active"):
                load_git_repository(7)

    def test_missing_url_raises(self) -> None:
        with (
            patch("workflow_steps.common.git_repository_loader.get_db_session") as session_factory,
            patch(
                "workflow_steps.common.git_repository_loader.GitRepositoryService"
            ) as service_cls,
        ):
            from workflow_steps.common.git_repository_loader import load_git_repository

            session_factory.return_value = MagicMock()
            service_cls.return_value.get_repository.return_value = {
                "id": 7,
                "name": "prod-configs",
                "url": "",
                "is_active": True,
            }

            with self.assertRaisesRegex(ValueError, "no URL configured"):
                load_git_repository(7)


if __name__ == "__main__":
    unittest.main()
