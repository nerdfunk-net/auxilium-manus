"""route-to-agent is registered consistently (registry, dispatch table, config)."""

from __future__ import annotations

import unittest
from pathlib import Path

from repositories.plugin_repository import PluginRepository
from services.execution.step_registry import STEP_REGISTRY
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from workflow_steps.route_to_agent.config import get_config
from workflow_steps.route_to_agent.executor import execute

STEP_ID = "route-to-agent"
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "workflow_steps" / "registry.yaml"


class RegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        registry = PluginRegistryService(PluginRepository(REGISTRY_PATH)).load_registry()
        cls.plugin = next((p for p in registry.plugins if p.id == STEP_ID), None)

    def test_registry_entry_is_in_the_routing_category(self) -> None:
        self.assertIsNotNone(self.plugin)
        self.assertEqual(self.plugin.name, "Route to Agent")
        self.assertEqual(self.plugin.artifact_type, "control_flow")
        self.assertEqual(self.plugin.palette_category, "routing")
        self.assertEqual(self.plugin.directory, "route_to_agent")
        self.assertTrue(self.plugin.enabled)

    def test_capability_contract_is_enrichment(self) -> None:
        self.assertEqual(self.plugin.requires, ["identity"])
        self.assertEqual(self.plugin.produces, ["attributes"])
        self.assertEqual([o.name for o in self.plugin.outcomes], ["success", "failure"])

    def test_dispatch_table_points_at_the_executor(self) -> None:
        self.assertIs(STEP_REGISTRY[STEP_ID], execute)

    def test_documented_config_inputs_match_default_config_keys(self) -> None:
        documented = {item.name for item in self.plugin.metadata.configuration_input}
        self.assertEqual(documented, set(get_config()))

    def test_required_inputs_are_marked(self) -> None:
        inputs = {item.name: item for item in self.plugin.metadata.configuration_input}
        for name in ("agent_source_id", "handler", "destination_path", "output_keys"):
            self.assertTrue(inputs[name].required, name)
        self.assertFalse(inputs["allow_missing_outputs"].required)


if __name__ == "__main__":
    unittest.main()
