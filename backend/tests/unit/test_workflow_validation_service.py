"""Tests for services/workflow/workflow_validation_service.py — Tiers 1-3, see
doc/ai_collaboration/VALIDATION_PLAN.md. Tier 2's external resolvers
(CredentialManager, load_git_repository) are mocked at the module boundary —
they have their own test coverage elsewhere; this file only tests that this
service calls them correctly and turns a failure into a finding."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from models.plugins import (
    PluginDefinition,
    PluginIOField,
    PluginMetadata,
    PluginRegistry,
    PluginStepOutcome,
)
from services.workflow.workflow_validation_service import WorkflowValidationService


def _registry(*plugins: PluginDefinition) -> PluginRegistry:
    return PluginRegistry(schema_version=1, plugins=list(plugins))


def _plugin(
    plugin_id: str,
    *,
    required_fields: list[str] | None = None,
    optional_fields: list[str] | None = None,
    field_defaults: dict[str, Any] | None = None,
    artifact_type: str = "generic",
    requires: list[str] | None = None,
    produces: list[str] | None = None,
    consumes: list[str] | None = None,
    requires_parsed: list[str] | None = None,
    produces_parsed: list[str] | None = None,
    outcomes: list[str] | None = None,
) -> PluginDefinition:
    defaults = field_defaults or {}
    fields = [
        PluginIOField(
            name=name,
            description=name,
            data_type="string",
            required=True,
            default=defaults.get(name),
        )
        for name in required_fields or []
    ] + [
        PluginIOField(
            name=name,
            description=name,
            data_type="string",
            required=False,
            default=defaults.get(name),
        )
        for name in optional_fields or []
    ]
    return PluginDefinition(
        id=plugin_id,
        name=plugin_id,
        overview="test",
        description="test",
        artifact_type=artifact_type,
        directory=plugin_id,
        requires=requires or [],
        produces=produces or [],
        consumes=consumes or [],
        requires_parsed=requires_parsed or [],
        produces_parsed=produces_parsed or [],
        outcomes=[PluginStepOutcome(name=name) for name in outcomes or []],
        metadata=PluginMetadata(configuration_input=fields),
    )


def _node(node_id: str, kind: str, plugin_config: dict | None = None) -> dict:
    return {"id": node_id, "data": {"kind": kind, "pluginConfig": plugin_config or {}}}


def _edge(source: str, target: str, source_handle: str = "success") -> dict:
    return {
        "id": f"{source}->{target}",
        "source": source,
        "target": target,
        "sourceHandle": source_handle,
        "targetHandle": "input",
    }


class _FakePluginRegistryService:
    """Duck-types the two PluginRegistryService methods WorkflowValidationService
    actually calls — no PluginRepository/on-disk registry.yaml needed for tests."""

    def __init__(
        self, registry: PluginRegistry, config_by_plugin_id: dict[str, dict[str, Any]] | None = None
    ) -> None:
        self._registry = registry
        self._config_by_plugin_id = config_by_plugin_id or {}

    def get_registry(self) -> PluginRegistry:
        return self._registry

    def get_plugin_config(self, plugin_id: str) -> dict[str, Any]:
        return self._config_by_plugin_id.get(plugin_id, {})


def _service(
    registry: PluginRegistry, config_by_plugin_id: dict[str, dict[str, Any]] | None = None
) -> WorkflowValidationService:
    svc = WorkflowValidationService(
        MagicMock(), _FakePluginRegistryService(registry, config_by_plugin_id)
    )
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

    def test_required_field_with_registry_default_is_not_an_error(self) -> None:
        """A required field the registry itself declares a non-blank
        `default:` for is never 'missing' — the step falls back to it."""
        registry = _registry(
            _plugin(
                "parse-cisco-config",
                required_fields=["output_key"],
                field_defaults={"output_key": "cisco_config"},
            )
        )
        svc = _service(registry)

        result = svc.validate([_node("n1", "parse-cisco-config", {})], acting_user_id=None)

        self.assertEqual(result.findings, [])

    def test_required_field_with_config_py_default_is_not_an_error(self) -> None:
        """Same as above, but the default lives in the step's config.py
        get_config() rather than registry.yaml's `default:` — this is how
        most steps' defaults are actually declared today."""
        registry = _registry(_plugin("parse-cisco-config", required_fields=["output_key"]))
        svc = _service(registry, {"parse-cisco-config": {"output_key": "cisco_config"}})

        result = svc.validate([_node("n1", "parse-cisco-config", {})], acting_user_id=None)

        self.assertEqual(result.findings, [])

    def test_required_field_with_blank_config_py_default_is_still_an_error(self) -> None:
        """A config.py default of "" or None doesn't actually provide a
        fallback value — the field is genuinely still missing."""
        registry = _registry(_plugin("run-command", required_fields=["command"]))
        svc = _service(registry, {"run-command": {"command": ""}})

        result = svc.validate([_node("n1", "run-command", {})], acting_user_id=None)

        self.assertTrue(result.has_errors)
        self.assertEqual(result.findings[0].code, "missing_required_field")

    def test_config_py_default_lookup_is_memoized_per_plugin_id(self) -> None:
        """get_plugin_config dynamically imports a config.py module — don't
        pay that cost once per node for a workflow with many nodes of the
        same kind."""
        registry = _registry(_plugin("run-command", required_fields=["command"]))
        get_plugin_config = MagicMock(return_value={"command": "show version"})
        svc = _service(registry)
        svc._plugin_registry_service.get_plugin_config = get_plugin_config

        svc.validate(
            [_node("n1", "run-command", {}), _node("n2", "run-command", {})],
            acting_user_id=None,
        )

        get_plugin_config.assert_called_once_with("run-command")


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


class Tier3CapabilityFlowTests(unittest.TestCase):
    def test_missing_capability_with_no_upstream_is_an_error(self) -> None:
        registry = _registry(_plugin("run-command", requires=["identity"], outcomes=["success"]))
        svc = _service(registry)

        result = svc.validate([_node("n1", "run-command")], acting_user_id=None)

        tier3 = [f for f in result.findings if f.tier == 3]
        self.assertEqual(len(tier3), 1)
        self.assertEqual(tier3[0].code, "missing_capability")
        self.assertEqual(tier3[0].node_id, "n1")

    def test_capability_satisfied_by_upstream_inventory_step_produces_no_findings(self) -> None:
        registry = _registry(
            _plugin(
                "get-nautobot-devices",
                artifact_type="inventory_selector",
                produces=["identity"],
                outcomes=["success", "failure"],
            ),
            _plugin("run-command", requires=["identity"], outcomes=["success"]),
        )
        svc = _service(registry)

        result = svc.validate(
            [_node("inv", "get-nautobot-devices"), _node("cmd", "run-command")],
            [_edge("inv", "cmd")],
            acting_user_id=None,
        )

        self.assertEqual([f for f in result.findings if f.tier == 3], [])

    def test_capability_only_on_one_branch_of_a_join_is_still_missing(self) -> None:
        """A join needs EVERY incoming branch to guarantee a capability — one
        branch producing it is not enough, since a device could have arrived
        via the other (VALIDATION_PLAN.md's intersection-at-joins rule)."""
        registry = _registry(
            _plugin(
                "inv",
                artifact_type="inventory_selector",
                produces=["identity"],
                outcomes=["success"],
            ),
            _plugin("adds-attributes", produces=["attributes"], outcomes=["success"]),
            _plugin("passthrough", outcomes=["success"]),
            _plugin("needs-attributes", requires=["attributes"], outcomes=["success"]),
        )
        svc = _service(registry)

        nodes = [
            _node("inv", "inv"),
            _node("a", "adds-attributes"),
            _node("b", "passthrough"),
            _node("join", "needs-attributes"),
        ]
        edges = [
            _edge("inv", "a"),
            _edge("inv", "b"),
            _edge("a", "join"),
            _edge("b", "join"),
        ]

        result = svc.validate(nodes, edges, acting_user_id=None)

        tier3 = [f for f in result.findings if f.tier == 3]
        self.assertEqual(len(tier3), 1)
        self.assertEqual(tier3[0].node_id, "join")
        self.assertEqual(tier3[0].code, "missing_capability")

    def test_capability_on_every_branch_of_a_join_produces_no_findings(self) -> None:
        registry = _registry(
            _plugin(
                "inv",
                artifact_type="inventory_selector",
                produces=["identity"],
                outcomes=["success"],
            ),
            _plugin("adds-attributes-1", produces=["attributes"], outcomes=["success"]),
            _plugin("adds-attributes-2", produces=["attributes"], outcomes=["success"]),
            _plugin("needs-attributes", requires=["attributes"], outcomes=["success"]),
        )
        svc = _service(registry)

        nodes = [
            _node("inv", "inv"),
            _node("a", "adds-attributes-1"),
            _node("b", "adds-attributes-2"),
            _node("join", "needs-attributes"),
        ]
        edges = [
            _edge("inv", "a"),
            _edge("inv", "b"),
            _edge("a", "join"),
            _edge("b", "join"),
        ]

        result = svc.validate(nodes, edges, acting_user_id=None)

        self.assertEqual([f for f in result.findings if f.tier == 3], [])

    def test_failure_outcome_does_not_carry_success_only_capability(self) -> None:
        """A step's `produces` is only guaranteed on its success outcome — a
        step wired off the failure branch must not inherit it."""
        registry = _registry(
            _plugin(
                "inv",
                artifact_type="inventory_selector",
                produces=["identity"],
                outcomes=["success", "failure"],
            ),
            _plugin("adds-attributes", produces=["attributes"], outcomes=["success", "failure"]),
            _plugin("needs-attributes", requires=["attributes"], outcomes=["success"]),
        )
        svc = _service(registry)

        nodes = [
            _node("inv", "inv"),
            _node("a", "adds-attributes"),
            _node("next", "needs-attributes"),
        ]
        edges = [
            _edge("inv", "a"),
            _edge("a", "next", source_handle="failure"),
        ]

        result = svc.validate(nodes, edges, acting_user_id=None)

        tier3 = [f for f in result.findings if f.tier == 3]
        self.assertEqual(len(tier3), 1)
        self.assertEqual(tier3[0].node_id, "next")

    def test_consumed_capability_is_no_longer_available_downstream(self) -> None:
        registry = _registry(
            _plugin(
                "inv",
                artifact_type="inventory_selector",
                produces=["identity", "attributes"],
                outcomes=["success"],
            ),
            _plugin("consumes-attributes", consumes=["attributes"], outcomes=["success"]),
            _plugin("needs-attributes", requires=["attributes"], outcomes=["success"]),
        )
        svc = _service(registry)

        nodes = [
            _node("inv", "inv"),
            _node("consumer", "consumes-attributes"),
            _node("next", "needs-attributes"),
        ]
        edges = [_edge("inv", "consumer"), _edge("consumer", "next")]

        result = svc.validate(nodes, edges, acting_user_id=None)

        tier3 = [f for f in result.findings if f.tier == 3]
        self.assertEqual(len(tier3), 1)
        self.assertEqual(tier3[0].node_id, "next")

    def test_effective_produces_is_config_aware_for_get_device_configs(self) -> None:
        """effective_produces (guards.py) is reused, not node.data.produces —
        get-device-configs only guarantees startup_config when config_format
        is 'startup', regardless of what the registry's static produces list
        says."""
        registry = _registry(
            _plugin(
                "inv",
                artifact_type="inventory_selector",
                produces=["identity"],
                outcomes=["success"],
            ),
            _plugin(
                "get-device-configs",
                produces=["running_config", "startup_config"],
                outcomes=["success"],
            ),
            _plugin("needs-running", requires=["running_config"], outcomes=["success"]),
        )
        svc = _service(registry)

        nodes = [
            _node("inv", "inv"),
            _node("configs", "get-device-configs", {"config_format": "startup"}),
            _node("next", "needs-running"),
        ]
        edges = [_edge("inv", "configs"), _edge("configs", "next")]

        result = svc.validate(nodes, edges, acting_user_id=None)

        tier3 = [f for f in result.findings if f.tier == 3]
        self.assertEqual(len(tier3), 1)
        self.assertEqual(tier3[0].node_id, "next")

    def test_missing_parsed_key_is_an_error(self) -> None:
        registry = _registry(
            _plugin(
                "inv",
                artifact_type="inventory_selector",
                produces=["identity"],
                outcomes=["success"],
            ),
            _plugin("run-command", outcomes=["success"]),
            _plugin("needs-parsed", requires_parsed=["interfaces"], outcomes=["success"]),
        )
        svc = _service(registry)

        nodes = [
            _node("inv", "inv"),
            _node("cmd", "run-command"),
            _node("next", "needs-parsed"),
        ]
        edges = [_edge("inv", "cmd"), _edge("cmd", "next")]

        result = svc.validate(nodes, edges, acting_user_id=None)

        tier3 = [f for f in result.findings if f.tier == 3]
        self.assertEqual(len(tier3), 1)
        self.assertEqual(tier3[0].code, "missing_parsed_key")

    def test_produces_parsed_satisfies_downstream_requires_parsed(self) -> None:
        registry = _registry(
            _plugin(
                "inv",
                artifact_type="inventory_selector",
                produces=["identity"],
                outcomes=["success"],
            ),
            _plugin(
                "run-command",
                produces_parsed=["interfaces"],
                outcomes=["success"],
            ),
            _plugin("needs-parsed", requires_parsed=["interfaces"], outcomes=["success"]),
        )
        svc = _service(registry)

        nodes = [
            _node("inv", "inv"),
            _node("cmd", "run-command"),
            _node("next", "needs-parsed"),
        ]
        edges = [_edge("inv", "cmd"), _edge("cmd", "next")]

        result = svc.validate(nodes, edges, acting_user_id=None)

        self.assertEqual([f for f in result.findings if f.tier == 3], [])

    def test_disabled_step_is_spliced_out_of_the_walk(self) -> None:
        registry = _registry(
            _plugin(
                "inv",
                artifact_type="inventory_selector",
                produces=["identity", "attributes"],
                outcomes=["success"],
            ),
            _plugin("adds-attributes", produces=["attributes"], outcomes=["success"]),
            _plugin("needs-attributes", requires=["attributes"], outcomes=["success"]),
        )
        svc = _service(registry)

        disabled_node = _node("a", "adds-attributes")
        disabled_node["data"]["disabled"] = True
        nodes = [_node("inv", "inv"), disabled_node, _node("next", "needs-attributes")]
        edges = [_edge("inv", "a"), _edge("a", "next")]

        result = svc.validate(nodes, edges, acting_user_id=None)

        # Still satisfied: inv already produces "attributes" directly, and the
        # disabled step being spliced out (rather than crashing the walk) is
        # exactly the point of this test.
        self.assertEqual([f for f in result.findings if f.tier == 3], [])

    def test_cycle_is_reported_as_a_single_finding_not_an_exception(self) -> None:
        registry = _registry(_plugin("run-command", outcomes=["success"]))
        svc = _service(registry)

        nodes = [_node("a", "run-command"), _node("b", "run-command")]
        edges = [_edge("a", "b"), _edge("b", "a")]

        result = svc.validate(nodes, edges, acting_user_id=None)

        tier3 = [f for f in result.findings if f.tier == 3]
        self.assertEqual(len(tier3), 1)
        self.assertEqual(tier3[0].code, "graph_cycle")

    def test_canvas_decoration_nodes_are_excluded_from_the_walk(self) -> None:
        registry = _registry(
            _plugin(
                "inv",
                artifact_type="inventory_selector",
                produces=["identity"],
                outcomes=["success"],
            ),
            _plugin("label", artifact_type="canvas_decoration", outcomes=[]),
        )
        # PluginDefinition has no `executable` override helper above; set it
        # directly since canvas decorations are marked non-executable.
        registry.plugins[1] = registry.plugins[1].model_copy(update={"executable": False})
        svc = _service(registry)

        nodes = [_node("inv", "inv"), _node("lbl", "label")]
        edges = [_edge("inv", "lbl")]

        result = svc.validate(nodes, edges, acting_user_id=None)

        self.assertEqual([f for f in result.findings if f.tier == 3], [])


class Tier4AttributePathWiringTests(unittest.TestCase):
    def test_reference_to_upstream_node_scoped_step_produces_no_findings(self) -> None:
        registry = _registry(
            _plugin("list-contains", outcomes=["success", "failure"]),
            _plugin("route-on-attribute", outcomes=["success"]),
        )
        svc = _service(registry)

        nodes = [
            _node("check", "list-contains"),
            _node("route", "route-on-attribute", {"attribute_path": "parsed.check.contains"}),
        ]
        edges = [_edge("check", "route")]

        result = svc.validate(nodes, edges, acting_user_id=None)

        self.assertEqual([f for f in result.findings if f.tier == 4], [])

    def test_reference_to_non_ancestor_node_scoped_step_is_a_warning(self) -> None:
        """The exact class of bug the device.parsed flat-key nesting fix was
        about: a plausible-looking reference that silently resolves to
        nothing because the referenced node isn't actually upstream."""
        registry = _registry(
            _plugin("list-contains", outcomes=["success"]),
            _plugin("route-on-attribute", outcomes=["success"]),
        )
        svc = _service(registry)

        # "check" and "route" are siblings off a common root — "check" is not
        # an ancestor of "route".
        nodes = [
            _node("root", "route-on-attribute"),
            _node("check", "list-contains"),
            _node("route", "route-on-attribute", {"attribute_path": "parsed.check.contains"}),
        ]
        edges = [_edge("root", "check"), _edge("root", "route")]

        result = svc.validate(nodes, edges, acting_user_id=None)

        tier4 = [f for f in result.findings if f.tier == 4]
        self.assertEqual(len(tier4), 1)
        self.assertEqual(tier4[0].severity, "warning")
        self.assertEqual(tier4[0].code, "stale_node_output_reference")
        self.assertEqual(tier4[0].node_id, "route")

    def test_self_reference_produces_no_findings(self) -> None:
        registry = _registry(_plugin("list-contains", outcomes=["success"]))
        svc = _service(registry)

        result = svc.validate(
            [_node("check", "list-contains", {"note": "parsed.check.contains"})],
            [],
            acting_user_id=None,
        )

        self.assertEqual([f for f in result.findings if f.tier == 4], [])

    def test_candidate_matching_a_non_node_scoped_step_is_never_guessed(self) -> None:
        """A candidate matching a real node id whose step kind does NOT use
        node_result.py (e.g. run-command) is ambiguous — never flagged."""
        registry = _registry(
            _plugin("run-command", outcomes=["success"]),
            _plugin("route-on-attribute", outcomes=["success"]),
        )
        svc = _service(registry)

        nodes = [
            _node("cmd", "run-command"),
            _node("route", "route-on-attribute", {"attribute_path": "parsed.cmd.output"}),
        ]
        edges = [_edge("cmd", "route")]

        result = svc.validate(nodes, edges, acting_user_id=None)

        self.assertEqual([f for f in result.findings if f.tier == 4], [])

    def test_ordinary_output_key_namespace_is_never_flagged(self) -> None:
        """A candidate not matching any node id at all is an ordinary
        parsed.<output_key> namespace (e.g. parse-cisco-config) — not a
        node-id reference, so there is nothing to check."""
        registry = _registry(_plugin("route-on-attribute", outcomes=["success"]))
        svc = _service(registry)

        result = svc.validate(
            [
                _node(
                    "route",
                    "route-on-attribute",
                    {"attribute_path": "parsed.cisco_config.running.hostname"},
                )
            ],
            [],
            acting_user_id=None,
        )

        self.assertEqual([f for f in result.findings if f.tier == 4], [])

    def test_reference_nested_inside_a_list_of_dicts_is_found(self) -> None:
        """update-attribute's `attributes: [{...}, {...}]` shape — string
        scanning must recurse into nested lists/dicts, not just top-level
        config values."""
        registry = _registry(
            _plugin("list-contains", outcomes=["success"]),
            _plugin("update-attribute", outcomes=["success"]),
        )
        svc = _service(registry)

        nodes = [
            _node("root", "update-attribute"),
            _node("check", "list-contains"),
            _node(
                "upd",
                "update-attribute",
                {"attributes": [{"mode": "regex", "source_path": "parsed.check.contains"}]},
            ),
        ]
        edges = [_edge("root", "check"), _edge("root", "upd")]

        result = svc.validate(nodes, edges, acting_user_id=None)

        tier4 = [f for f in result.findings if f.tier == 4]
        self.assertEqual(len(tier4), 1)
        self.assertEqual(tier4[0].node_id, "upd")

    def test_reference_inside_a_jinja_placeholder_is_found(self) -> None:
        registry = _registry(
            _plugin("list-contains", outcomes=["success"]),
            _plugin("render-jinja-template", outcomes=["success"]),
        )
        svc = _service(registry)

        nodes = [
            _node("root", "render-jinja-template"),
            _node("check", "list-contains"),
            _node(
                "tmpl",
                "render-jinja-template",
                {"template": "Result: {{ parsed.check.contains }}"},
            ),
        ]
        edges = [_edge("root", "check"), _edge("root", "tmpl")]

        result = svc.validate(nodes, edges, acting_user_id=None)

        tier4 = [f for f in result.findings if f.tier == 4]
        self.assertEqual(len(tier4), 1)
        self.assertEqual(tier4[0].node_id, "tmpl")


class RealRegistryDefaultRegressionTests(unittest.TestCase):
    """Regression tests against the real registry.yaml + config.py for two
    reported false positives — see the "default keys" discussion in
    doc/ai_collaboration/VALIDATION_PLAN.md. Uses the real PluginRegistryService
    (unlike every other test class here, which builds an in-memory fake
    registry), so a real registry.yaml/config.py edit that reintroduces
    either bug fails this test, not just a hand-built fixture."""

    def setUp(self) -> None:
        from pathlib import Path

        from repositories.plugin_repository import PluginRepository
        from services.plugin_registry.plugin_registry_service import PluginRegistryService

        registry_path = Path(__file__).resolve().parents[2] / "workflow_steps" / "registry.yaml"
        self.service = PluginRegistryService(PluginRepository(registry_path))

    def _service(self) -> WorkflowValidationService:
        svc = WorkflowValidationService(MagicMock(), self.service)
        svc._settings_repo = MagicMock()
        return svc

    def test_get_nautobot_attributes_with_no_optional_groups_is_valid(self) -> None:
        svc = self._service()

        result = svc.validate(
            [
                _node(
                    "n1",
                    "get-nautobot-attributes",
                    {"nautobot_source_id": "prod-lab", "list_of_attributes": []},
                )
            ],
            acting_user_id=None,
        )

        self.assertEqual([f for f in result.findings if f.tier == 1], [])

    def test_get_nautobot_attributes_with_missing_list_key_is_valid(self) -> None:
        """The exact shape of the originally reported bug: an older-saved
        node where list_of_attributes is entirely absent from pluginConfig,
        not merely an empty list."""
        svc = self._service()

        result = svc.validate(
            [_node("n1", "get-nautobot-attributes", {"nautobot_source_id": "prod-lab"})],
            acting_user_id=None,
        )

        self.assertEqual([f for f in result.findings if f.tier == 1], [])

    def test_parse_cisco_config_with_missing_output_key_is_valid(self) -> None:
        svc = self._service()

        result = svc.validate(
            [_node("n1", "parse-cisco-config", {"config_source": "both"})],
            acting_user_id=None,
        )

        self.assertEqual([f for f in result.findings if f.tier == 1], [])

    def test_parse_cisco_config_with_missing_config_source_is_also_valid(self) -> None:
        svc = self._service()

        result = svc.validate(
            [_node("n1", "parse-cisco-config", {"output_key": "cisco_config"})],
            acting_user_id=None,
        )

        self.assertEqual([f for f in result.findings if f.tier == 1], [])


if __name__ == "__main__":
    unittest.main()
