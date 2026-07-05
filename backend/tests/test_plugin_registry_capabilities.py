"""Tests for capability-aware plugin registry loading."""

from __future__ import annotations

import unittest
from pathlib import Path

from models.plugins import PluginDefinition, PluginRegistry
from models.workflow_context import Capability
from repositories.plugin_repository import PluginRepository
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from services.workflow_context.registry import capability_spec_from_plugin

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "workflow_steps" / "registry.yaml"


class PluginRegistryCapabilityTests(unittest.TestCase):
    def test_registry_loads_capability_fields(self) -> None:
        service = PluginRegistryService(PluginRepository(REGISTRY_PATH))
        registry = service.load_registry()
        self.assertIsInstance(registry, PluginRegistry)
        self.assertGreater(len(registry.plugins), 0)

        nautobot_devices = next(p for p in registry.plugins if p.id == "get-nautobot-devices")
        self.assertEqual(nautobot_devices.requires, [])
        self.assertEqual(nautobot_devices.produces, ["identity"])
        self.assertEqual([o.name for o in nautobot_devices.outcomes], ["success", "failure"])

    def test_capability_strings_match_enum(self) -> None:
        service = PluginRegistryService(PluginRepository(REGISTRY_PATH))
        registry = service.load_registry()
        enum_values = {cap.value for cap in Capability}

        for plugin in registry.plugins:
            for field_name in ("requires", "produces", "consumes"):
                for value in getattr(plugin, field_name):
                    self.assertIn(value, enum_values, f"{plugin.id}.{field_name}")

    def test_capability_spec_from_plugin(self) -> None:
        plugin = PluginDefinition.model_validate(
            {
                "id": "parse-bgp",
                "name": "Parse BGP",
                "overview": "Parse BGP routes.",
                "description": "x",
                "artifact_type": "configuration_retrieval",
                "directory": "parse_bgp",
                "requires": ["running_config"],
                "produces": ["parsed"],
                "requires_parsed": ["bgp"],
                "produces_parsed": ["bgp"],
                "outcomes": [{"name": "success"}],
                "metadata": {
                    "configuration_input": [],
                },
            }
        )
        spec = capability_spec_from_plugin(plugin)
        self.assertIn(Capability.RUNNING_CONFIG, spec.requires)
        self.assertIn(Capability.PARSED, spec.produces)
        self.assertIn("bgp", spec.requires_parsed)


    def test_git_steps_require_identity(self) -> None:
        service = PluginRegistryService(PluginRepository(REGISTRY_PATH))
        registry = service.load_registry()
        for step_id in ("git-clone", "git-pull", "git-push"):
            plugin = next(p for p in registry.plugins if p.id == step_id)
            self.assertEqual(plugin.requires, ["identity"], step_id)
            self.assertEqual(plugin.produces, [], step_id)

    def test_get_git_devices_has_no_input_requirement(self) -> None:
        service = PluginRegistryService(PluginRepository(REGISTRY_PATH))
        registry = service.load_registry()
        plugin = next(p for p in registry.plugins if p.id == "get-git-devices")
        self.assertEqual(plugin.requires, [])


if __name__ == "__main__":
    unittest.main()
