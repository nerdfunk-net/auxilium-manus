"""Tests for settings git source loader."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from workflow_steps.common.git_source_loader import load_git_source_repository


class GitSourceLoaderTests(unittest.TestCase):
    def test_loads_repository_dict_from_settings(self) -> None:
        setting = MagicMock()
        setting.value = {
            "url": "https://example.com/repo.git",
            "branch": "main",
            "token": "secret",
            "username": "gituser",
            "repository_path": "configs",
        }

        with patch(
            "workflow_steps.common.git_source_loader.get_db_session"
        ) as session_factory, patch(
            "workflow_steps.common.git_source_loader.SettingsRepository"
        ) as repo_cls:
            session = MagicMock()
            session_factory.return_value = session
            repo_cls.return_value.get_by_key.return_value = setting

            repository = load_git_source_repository("prod-configs")

        self.assertEqual(repository["source_id"], "prod-configs")
        self.assertEqual(repository["url"], "https://example.com/repo.git")
        self.assertEqual(repository["token"], "secret")
        self.assertEqual(repository["path"], "configs")

    def test_missing_setting_raises(self) -> None:
        with patch(
            "workflow_steps.common.git_source_loader.get_db_session"
        ) as session_factory, patch(
            "workflow_steps.common.git_source_loader.SettingsRepository"
        ) as repo_cls:
            session_factory.return_value = MagicMock()
            repo_cls.return_value.get_by_key.return_value = None

            with self.assertRaisesRegex(ValueError, "not found in settings"):
                load_git_source_repository("missing")


if __name__ == "__main__":
    unittest.main()
