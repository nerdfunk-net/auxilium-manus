"""get-from-agent is registered consistently (registry, dispatch table, config)."""

from __future__ import annotations

import unittest
from pathlib import Path

from repositories.plugin_repository import PluginRepository
from services.execution.step_registry import STEP_REGISTRY
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from workflow_steps.get_from_agent.config import get_config
from workflow_steps.get_from_agent.executor import execute

STEP_ID = "get-from-agent"
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "workflow_steps" / "registry.yaml"


class RegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        registry = PluginRegistryService(PluginRepository(REGISTRY_PATH)).load_registry()
        cls.plugin = next((p for p in registry.plugins if p.id == STEP_ID), None)

    def test_registry_entry_is_an_inventory_selector(self) -> None:
        self.assertIsNotNone(self.plugin)
        self.assertEqual(self.plugin.name, "Get from Agent")
        self.assertEqual(self.plugin.artifact_type, "inventory_selector")
        self.assertEqual(self.plugin.directory, "get_from_agent")
        self.assertTrue(self.plugin.enabled)

    def test_capability_contract_is_identity_source(self) -> None:
        self.assertEqual(self.plugin.requires, [])
        self.assertEqual(self.plugin.produces, ["identity"])
        self.assertEqual([o.name for o in self.plugin.outcomes], ["success"])

    def test_dispatch_table_points_at_the_executor(self) -> None:
        self.assertIs(STEP_REGISTRY[STEP_ID], execute)

    def test_documented_config_inputs_match_default_config_keys(self) -> None:
        documented = {item.name for item in self.plugin.metadata.configuration_input}
        self.assertEqual(documented, set(get_config()))

    def test_required_inputs_are_marked(self) -> None:
        inputs = {item.name: item for item in self.plugin.metadata.configuration_input}
        for name in ("agent_source_id", "handler"):
            self.assertTrue(inputs[name].required, name)
        self.assertFalse(inputs["attributes"].required)


if __name__ == "__main__":
    unittest.main()
