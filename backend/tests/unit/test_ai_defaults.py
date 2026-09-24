"""Tests for scripts/ai_defaults.py — the live resolver/drift-checker for
doc/ai_collaboration/AI_DEFAULTS.md, see doc/ai_collaboration/PROCESS.md. External
resolvers (CredentialsService, GitRepositoryService, SettingsRepository,
InventoryRepository) are mocked at the module boundary, same convention as
tests/unit/test_workflow_validation_service.py."""

from __future__ import annotations

import unittest
from unittest.mock import DEFAULT, MagicMock, patch

from scripts.ai_defaults import (
    AiDefaultsDriftError,
    load_ai_defaults_yaml,
    resolve_and_check,
)


def _credential(name: str, cred_type: str, cred_id: int = 1) -> dict:
    return {"id": cred_id, "name": name, "type": cred_type}


def _repo(name: str, category: str, repo_id: int = 1) -> dict:
    return {"id": repo_id, "name": name, "category": category, "is_active": True}


class LoadAiDefaultsYamlTests(unittest.TestCase):
    def test_real_file_has_expected_top_level_sections(self) -> None:
        raw = load_ai_defaults_yaml()
        self.assertIn("policy", raw)
        self.assertIn("credentials", raw)
        self.assertIn("git_repositories", raw)
        self.assertIn("sources", raw)
        self.assertIn("inventories", raw)
        # Every credential entry has both a name and a type — the two fields
        # resolve_and_check relies on.
        for key, entry in raw["credentials"].items():
            self.assertIn("name", entry, key)
            self.assertIn("type", entry, key)


class ResolveAndCheckTests(unittest.TestCase):
    def _patched(self):
        return patch.multiple(
            "scripts.ai_defaults",
            CredentialsService=DEFAULT,
            GitRepositoryService=DEFAULT,
            SettingsRepository=DEFAULT,
            InventoryRepository=DEFAULT,
        )

    def _fake_yaml(self, **overrides):
        base = {
            "policy": {"visibility": "private"},
            "credentials": {"ssh_default": {"name": "cisco - noc", "type": "ssh"}},
            "git_repositories": {"device_configs": "device-configs"},
            "sources": {"nautobot_source_id": "nautobot"},
            "inventories": {"safe_default": "LAB"},
        }
        base.update(overrides)
        return base

    def test_all_entries_resolve_returns_ids(self) -> None:
        with self._patched() as mocks, patch(
            "scripts.ai_defaults.load_ai_defaults_yaml", return_value=self._fake_yaml()
        ):
            mocks["CredentialsService"].return_value.list_credentials.return_value = [
                _credential("cisco - noc", "ssh", cred_id=5)
            ]
            mocks["GitRepositoryService"].return_value.get_repositories.return_value = [
                _repo("device-configs", "device_configs", repo_id=9)
            ]
            mocks["SettingsRepository"].return_value.get_by_key.return_value = MagicMock()
            inventory = MagicMock(id=1)
            mocks["InventoryRepository"].return_value.get_by_name.return_value = inventory

            resolved = resolve_and_check(db=MagicMock(), acting_username="ai-assistant")

        self.assertEqual(resolved.credentials["ssh_default"]["id"], 5)
        self.assertEqual(resolved.git_repository_ids["device_configs"], 9)
        self.assertEqual(resolved.sources["nautobot_source_id"], "nautobot")
        self.assertEqual(resolved.inventory_ids["safe_default"], 1)

    def test_missing_credential_raises_drift_error(self) -> None:
        with self._patched() as mocks, patch(
            "scripts.ai_defaults.load_ai_defaults_yaml", return_value=self._fake_yaml()
        ):
            mocks["CredentialsService"].return_value.list_credentials.return_value = []

            with self.assertRaises(AiDefaultsDriftError) as ctx:
                resolve_and_check(db=MagicMock(), acting_username="ai-assistant")

        self.assertIn("ssh_default", str(ctx.exception))
        self.assertIn("cisco - noc", str(ctx.exception))

    def test_credential_wrong_type_raises_drift_error(self) -> None:
        with self._patched() as mocks, patch(
            "scripts.ai_defaults.load_ai_defaults_yaml", return_value=self._fake_yaml()
        ):
            mocks["CredentialsService"].return_value.list_credentials.return_value = [
                _credential("cisco - noc", "generic", cred_id=5)
            ]

            with self.assertRaises(AiDefaultsDriftError):
                resolve_and_check(db=MagicMock(), acting_username="ai-assistant")

    def test_missing_git_repository_raises_drift_error(self) -> None:
        with self._patched() as mocks, patch(
            "scripts.ai_defaults.load_ai_defaults_yaml", return_value=self._fake_yaml()
        ):
            mocks["CredentialsService"].return_value.list_credentials.return_value = [
                _credential("cisco - noc", "ssh", cred_id=5)
            ]
            mocks["GitRepositoryService"].return_value.get_repositories.return_value = []

            with self.assertRaises(AiDefaultsDriftError) as ctx:
                resolve_and_check(db=MagicMock(), acting_username="ai-assistant")

        self.assertIn("device_configs", str(ctx.exception))

    def test_missing_source_raises_drift_error(self) -> None:
        with self._patched() as mocks, patch(
            "scripts.ai_defaults.load_ai_defaults_yaml", return_value=self._fake_yaml()
        ):
            mocks["CredentialsService"].return_value.list_credentials.return_value = [
                _credential("cisco - noc", "ssh", cred_id=5)
            ]
            mocks["GitRepositoryService"].return_value.get_repositories.return_value = [
                _repo("device-configs", "device_configs", repo_id=9)
            ]
            mocks["SettingsRepository"].return_value.get_by_key.return_value = None

            with self.assertRaises(AiDefaultsDriftError) as ctx:
                resolve_and_check(db=MagicMock(), acting_username="ai-assistant")

        self.assertIn("nautobot_source_id", str(ctx.exception))

    def test_missing_inventory_raises_drift_error(self) -> None:
        with self._patched() as mocks, patch(
            "scripts.ai_defaults.load_ai_defaults_yaml", return_value=self._fake_yaml()
        ):
            mocks["CredentialsService"].return_value.list_credentials.return_value = [
                _credential("cisco - noc", "ssh", cred_id=5)
            ]
            mocks["GitRepositoryService"].return_value.get_repositories.return_value = [
                _repo("device-configs", "device_configs", repo_id=9)
            ]
            mocks["SettingsRepository"].return_value.get_by_key.return_value = MagicMock()
            mocks["InventoryRepository"].return_value.get_by_name.return_value = None

            with self.assertRaises(AiDefaultsDriftError) as ctx:
                resolve_and_check(db=MagicMock(), acting_username="ai-assistant")

        self.assertIn("safe_default", str(ctx.exception))
        self.assertIn("LAB", str(ctx.exception))


class RealAiDefaultsYamlRegressionTests(unittest.TestCase):
    """Loads the real ai_defaults.yaml (not a fixture) against mocked live
    lookups that always succeed, to catch a malformed real file — e.g. a
    credential entry missing 'type', or a category typo — that only a schema
    mismatch (not a unit fixture) would expose."""

    def test_real_file_resolves_against_a_permissive_fake_db(self) -> None:
        raw = load_ai_defaults_yaml()

        with patch.multiple(
            "scripts.ai_defaults",
            CredentialsService=DEFAULT,
            GitRepositoryService=DEFAULT,
            SettingsRepository=DEFAULT,
            InventoryRepository=DEFAULT,
        ) as mocks:
            mocks["CredentialsService"].return_value.list_credentials.return_value = [
                _credential(entry["name"], entry["type"])
                for entry in raw["credentials"].values()
            ]
            mocks["GitRepositoryService"].return_value.get_repositories.side_effect = (
                lambda category, active_only=True: [
                    _repo(raw["git_repositories"][category], category)
                ]
            )
            mocks["SettingsRepository"].return_value.get_by_key.return_value = MagicMock()
            mocks["InventoryRepository"].return_value.get_by_name.return_value = MagicMock(id=1)

            resolved = resolve_and_check(db=MagicMock(), acting_username="ai-assistant")

        self.assertEqual(set(resolved.credentials), set(raw["credentials"]))
        self.assertEqual(set(resolved.git_repository_ids), set(raw["git_repositories"]))
        self.assertEqual(set(resolved.sources), set(raw["sources"]))
        self.assertEqual(set(resolved.inventory_ids), set(raw["inventories"]))


if __name__ == "__main__":
    unittest.main()
