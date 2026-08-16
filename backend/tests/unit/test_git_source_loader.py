"""Tests for settings git source loader."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from services.settings.exceptions import SourceConfigError
from workflow_steps.common.git_source_loader import load_git_source_repository


class GitSourceLoaderTests(unittest.TestCase):
    def test_loads_repository_dict_from_settings(self) -> None:
        with (
            patch("workflow_steps.common.git_source_loader.get_db_session") as session_factory,
            patch(
                "workflow_steps.common.git_source_loader.SettingsService"
            ) as settings_service_cls,
        ):
            session_factory.return_value = MagicMock()
            settings_service_cls.return_value.get_source_config_for_step.return_value = {
                "url": "https://example.com/repo.git",
                "branch": "main",
                "token": "secret",
                "username": "gituser",
                "repository_path": "configs",
                "verify_ssl": True,
                "source_id": "prod-configs",
            }

            repository = load_git_source_repository("prod-configs")

        self.assertEqual(repository["source_id"], "prod-configs")
        self.assertEqual(repository["url"], "https://example.com/repo.git")
        self.assertEqual(repository["token"], "secret")
        self.assertEqual(repository["path"], "configs")
        self.assertTrue(repository["verify_ssl"])

    def test_propagates_verify_ssl_false_from_settings(self) -> None:
        with (
            patch("workflow_steps.common.git_source_loader.get_db_session") as session_factory,
            patch(
                "workflow_steps.common.git_source_loader.SettingsService"
            ) as settings_service_cls,
        ):
            session_factory.return_value = MagicMock()
            settings_service_cls.return_value.get_source_config_for_step.return_value = {
                "url": "https://example.com/repo.git",
                "branch": "main",
                "token": "secret",
                "verify_ssl": False,
                "source_id": "lab-configs",
            }

            repository = load_git_source_repository("lab-configs")

        self.assertFalse(repository["verify_ssl"])

    def test_resolves_credential_id_backed_token(self) -> None:
        """A source saved through the Settings UI stores its secret as credential_id;
        SettingsService (not a raw settings lookup) is what decrypts it into a token."""
        with (
            patch("workflow_steps.common.git_source_loader.get_db_session") as session_factory,
            patch(
                "workflow_steps.common.git_source_loader.SettingsService"
            ) as settings_service_cls,
        ):
            session_factory.return_value = MagicMock()
            settings_service_cls.return_value.get_source_config_for_step.return_value = {
                "url": "https://example.com/repo.git",
                "branch": "main",
                "token": "decrypted-from-credential-store",
                "source_id": "prod-configs",
            }

            repository = load_git_source_repository("prod-configs")

        settings_service_cls.return_value.get_source_config_for_step.assert_called_once_with(
            "git", "prod-configs"
        )
        self.assertEqual(repository["token"], "decrypted-from-credential-store")

    def test_missing_setting_raises(self) -> None:
        with (
            patch("workflow_steps.common.git_source_loader.get_db_session") as session_factory,
            patch(
                "workflow_steps.common.git_source_loader.SettingsService"
            ) as settings_service_cls,
        ):
            session_factory.return_value = MagicMock()
            settings_service_cls.return_value.get_source_config_for_step.side_effect = (
                SourceConfigError("git source 'missing' not found in settings")
            )

            with self.assertRaisesRegex(ValueError, "not found in settings"):
                load_git_source_repository("missing")


if __name__ == "__main__":
    unittest.main()
