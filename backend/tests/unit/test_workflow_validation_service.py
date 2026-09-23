"""Tests for services/workflow/workflow_validation_service.py — Tiers 1-2 only,
see doc/ai_workflows/VALIDATION_PLAN.md. Tier 2's external resolvers
(CredentialManager, load_git_repository) are mocked at the module boundary —
they have their own test coverage elsewhere; this file only tests that this
service calls them correctly and turns a failure into a finding."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from models.plugins import PluginDefinition, PluginIOField, PluginMetadata, PluginRegistry
from services.workflow.workflow_validation_service import WorkflowValidationService


def _registry(*plugins: PluginDefinition) -> PluginRegistry:
    return PluginRegistry(schema_version=1, plugins=list(plugins))


def _plugin(
    plugin_id: str,
    *,
    required_fields: list[str],
    optional_fields: list[str] | None = None,
) -> PluginDefinition:
    fields = [
        PluginIOField(name=name, description=name, data_type="string", required=True)
        for name in required_fields
    ] + [
        PluginIOField(name=name, description=name, data_type="string", required=False)
        for name in optional_fields or []
    ]
    return PluginDefinition(
        id=plugin_id,
        name=plugin_id,
        overview="test",
        description="test",
        artifact_type="generic",
        directory=plugin_id,
        outcomes=[],
        metadata=PluginMetadata(configuration_input=fields),
    )


def _node(node_id: str, kind: str, plugin_config: dict) -> dict:
    return {"id": node_id, "data": {"kind": kind, "pluginConfig": plugin_config}}


def _service(registry: PluginRegistry) -> WorkflowValidationService:
    svc = WorkflowValidationService(MagicMock(), registry)
    svc._settings_repo = MagicMock()
    return svc


class Tier1SchemaTests(unittest.TestCase):
    def test_unknown_step_kind_is_an_error(self) -> None:
        svc = _service(_registry())
        result = svc.validate([_node("n1", "not-a-real-step", {})], acting_user_id=None)

        self.assertTrue(result.has_errors)
        self.assertEqual(result.findings[0].code, "unknown_step_kind")

    def test_missing_required_field_is_an_error(self) -> None:
        registry = _registry(_plugin("run-command", required_fields=["command"]))
        svc = _service(registry)

        result = svc.validate([_node("n1", "run-command", {})], acting_user_id=None)

        self.assertTrue(result.has_errors)
        self.assertEqual(result.findings[0].code, "missing_required_field")
        self.assertEqual(result.findings[0].tier, 1)

    def test_blank_string_required_field_is_an_error(self) -> None:
        registry = _registry(_plugin("run-command", required_fields=["command"]))
        svc = _service(registry)

        result = svc.validate(
            [_node("n1", "run-command", {"command": "   "})], acting_user_id=None
        )

        self.assertTrue(result.has_errors)

    def test_present_required_field_produces_no_findings(self) -> None:
        registry = _registry(_plugin("run-command", required_fields=["command"]))
        svc = _service(registry)

        result = svc.validate(
            [_node("n1", "run-command", {"command": "show version"})], acting_user_id=None
        )

        self.assertEqual(result.findings, [])
        self.assertFalse(result.has_errors)

    def test_missing_optional_field_produces_no_findings(self) -> None:
        registry = _registry(
            _plugin("run-command", required_fields=[], optional_fields=["timeout"])
        )
        svc = _service(registry)

        result = svc.validate([_node("n1", "run-command", {})], acting_user_id=None)

        self.assertEqual(result.findings, [])


def _credential(name: str, cred_type: str, *, visibility: str = "global", status: str = "active"):
    return {"name": name, "type": cred_type, "visibility": visibility, "status": status}


class Tier2ReferenceTests(unittest.TestCase):
    def test_credential_reference_not_found_is_an_error(self) -> None:
        registry = _registry(_plugin("run-command", required_fields=[]))
        svc = _service(registry)

        with patch(
            "services.workflow.workflow_validation_service.CredentialsService"
        ) as mock_service_cls:
            mock_service_cls.return_value.list_credentials.return_value = []
            result = svc.validate(
                [_node("n1", "run-command", {"credential_reference": "missing"})],
                acting_user_id=7,
            )

        self.assertTrue(result.has_errors)
        self.assertEqual(result.findings[0].code, "credential_reference_not_found")
        self.assertEqual(result.findings[0].tier, 2)

    def test_credential_reference_found_produces_no_findings(self) -> None:
        registry = _registry(_plugin("run-command", required_fields=[]))
        svc = _service(registry)

        with patch(
            "services.workflow.workflow_validation_service.CredentialsService"
        ) as mock_service_cls:
            mock_service_cls.return_value.list_credentials.return_value = [
                _credential("cisco - noc", "ssh")
            ]
            result = svc.validate(
                [_node("n1", "run-command", {"credential_reference": "cisco - noc"})],
                acting_user_id=7,
            )

        self.assertEqual(result.findings, [])

    def test_credential_wrong_type_is_an_error(self) -> None:
        registry = _registry(_plugin("run-command", required_fields=[]))
        svc = _service(registry)

        with patch(
            "services.workflow.workflow_validation_service.CredentialsService"
        ) as mock_service_cls:
            mock_service_cls.return_value.list_credentials.return_value = [
                _credential("token-cred", "generic")
            ]
            result = svc.validate(
                [_node("n1", "run-command", {"credential_reference": "token-cred"})],
                acting_user_id=7,
            )

        self.assertTrue(result.has_errors)
        self.assertEqual(result.findings[0].code, "credential_reference_wrong_type")

    def test_expired_credential_is_an_error(self) -> None:
        registry = _registry(_plugin("run-command", required_fields=[]))
        svc = _service(registry)

        with patch(
            "services.workflow.workflow_validation_service.CredentialsService"
        ) as mock_service_cls:
            mock_service_cls.return_value.list_credentials.return_value = [
                _credential("cisco - noc", "ssh", status="expired")
            ]
            result = svc.validate(
                [_node("n1", "run-command", {"credential_reference": "cisco - noc"})],
                acting_user_id=7,
            )

        self.assertTrue(result.has_errors)
        self.assertEqual(result.findings[0].code, "credential_reference_expired")

    def test_private_credential_preferred_over_global_of_same_name(self) -> None:
        registry = _registry(_plugin("run-command", required_fields=[]))
        svc = _service(registry)

        with patch(
            "services.workflow.workflow_validation_service.CredentialsService"
        ) as mock_service_cls:
            mock_service_cls.return_value.list_credentials.return_value = [
                _credential("shared", "generic", visibility="global"),
                _credential("shared", "ssh", visibility="private"),
            ]
            result = svc.validate(
                [_node("n1", "run-command", {"credential_reference": "shared"})],
                acting_user_id=7,
            )

        # If the global (wrong-type) match won instead of the private one,
        # this would be a wrong_type finding.
        self.assertEqual(result.findings, [])

    def test_shared_secret_step_kind_requires_shared_secret_type(self) -> None:
        registry = _registry(_plugin("encrypt-attribute", required_fields=[]))
        svc = _service(registry)

        with patch(
            "services.workflow.workflow_validation_service.CredentialsService"
        ) as mock_service_cls:
            mock_service_cls.return_value.list_credentials.return_value = [
                _credential("shared-secret", "shared_secret")
            ]
            result = svc.validate(
                [_node("n1", "encrypt-attribute", {"credential_reference": "shared-secret"})],
                acting_user_id=7,
            )

        self.assertEqual(result.findings, [])

    def test_validation_module_never_imports_credential_manager(self) -> None:
        # Tier 2 must be a metadata-only existence check — CredentialManager
        # decrypts the secret as a side effect of resolving it, which a
        # workflows:read-gated endpoint must never trigger. Regression guard
        # against re-introducing that import.
        import services.workflow.workflow_validation_service as mod

        self.assertFalse(hasattr(mod, "CredentialManager"))

    def test_git_repository_not_found_is_an_error(self) -> None:
        registry = _registry(_plugin("git-clone", required_fields=[]))
        svc = _service(registry)

        with patch(
            "services.workflow.workflow_validation_service.GitRepositoryService"
        ) as mock_service_cls:
            mock_service_cls.return_value.get_repository.return_value = None
            result = svc.validate(
                [_node("n1", "git-clone", {"git_repository_id": 999})], acting_user_id=None
            )

        self.assertTrue(result.has_errors)
        self.assertEqual(result.findings[0].code, "git_repository_not_found")

    def test_git_repository_inactive_is_an_error(self) -> None:
        registry = _registry(_plugin("git-clone", required_fields=[]))
        svc = _service(registry)

        with patch(
            "services.workflow.workflow_validation_service.GitRepositoryService"
        ) as mock_service_cls:
            mock_service_cls.return_value.get_repository.return_value = {
                "id": 4,
                "name": "device-configs",
                "is_active": False,
                "url": "https://example.com/repo.git",
            }
            result = svc.validate(
                [_node("n1", "git-clone", {"git_repository_id": 4})], acting_user_id=None
            )

        self.assertTrue(result.has_errors)
        self.assertEqual(result.findings[0].code, "git_repository_not_found")

    def test_git_repository_found_produces_no_findings(self) -> None:
        registry = _registry(_plugin("git-clone", required_fields=[]))
        svc = _service(registry)

        with patch(
            "services.workflow.workflow_validation_service.GitRepositoryService"
        ) as mock_service_cls:
            mock_service_cls.return_value.get_repository.return_value = {
                "id": 4,
                "name": "device-configs",
                "is_active": True,
                "url": "https://example.com/repo.git",
            }
            result = svc.validate(
                [_node("n1", "git-clone", {"git_repository_id": 4})], acting_user_id=None
            )

        self.assertEqual(result.findings, [])

    def test_source_id_not_found_is_an_error(self) -> None:
        registry = _registry(_plugin("get-nautobot-devices", required_fields=[]))
        svc = _service(registry)
        svc._settings_repo.get_by_key.return_value = None

        result = svc.validate(
            [_node("n1", "get-nautobot-devices", {"nautobot_source_id": "missing"})],
            acting_user_id=None,
        )

        self.assertTrue(result.has_errors)
        self.assertEqual(result.findings[0].code, "source_not_found")
        svc._settings_repo.get_by_key.assert_called_once_with("sources.nautobot.missing")

    def test_source_id_found_produces_no_findings(self) -> None:
        registry = _registry(_plugin("get-nautobot-devices", required_fields=[]))
        svc = _service(registry)
        svc._settings_repo.get_by_key.return_value = MagicMock()

        result = svc.validate(
            [_node("n1", "get-nautobot-devices", {"nautobot_source_id": "nautobot"})],
            acting_user_id=None,
        )

        self.assertEqual(result.findings, [])


if __name__ == "__main__":
    unittest.main()
