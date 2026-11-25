"""get-catalyst-center-devices is registered consistently (registry, dispatch table, config)."""

from __future__ import annotations

import unittest
from pathlib import Path

from repositories.plugin_repository import PluginRepository
from services.execution.step_registry import STEP_REGISTRY
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from workflow_steps.get_catalyst_center_devices.config import get_config
from workflow_steps.get_catalyst_center_devices.executor import execute

STEP_ID = "get-catalyst-center-devices"
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "workflow_steps" / "registry.yaml"


class RegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        registry = PluginRegistryService(PluginRepository(REGISTRY_PATH)).load_registry()
        cls.plugin = next((p for p in registry.plugins if p.id == STEP_ID), None)

    def test_registry_entry_exists_in_the_cisco_inventory_slot(self) -> None:
        self.assertIsNotNone(self.plugin)
        self.assertEqual(self.plugin.name, "Get from Catalyst Center")
        self.assertEqual(self.plugin.artifact_type, "inventory_selector")
        self.assertEqual(self.plugin.palette_category, "cisco")
        self.assertEqual(self.plugin.directory, "get_catalyst_center_devices")
        self.assertTrue(self.plugin.enabled)

    def test_capability_contract_matches_other_inventory_steps(self) -> None:
        self.assertEqual(self.plugin.requires, [])
        self.assertEqual(self.plugin.produces, ["identity"])
        self.assertEqual([o.name for o in self.plugin.outcomes], ["success", "failure"])

    def test_dispatch_table_points_at_the_executor(self) -> None:
        self.assertIs(STEP_REGISTRY[STEP_ID], execute)

    def test_documented_config_inputs_match_default_config_keys(self) -> None:
        documented = {item.name for item in self.plugin.metadata.configuration_input}
        self.assertEqual(documented, set(get_config()))

    def test_source_and_guard_inputs_are_described(self) -> None:
        inputs = {item.name: item for item in self.plugin.metadata.configuration_input}
        self.assertTrue(inputs["catalyst_center_source_id"].required)
        self.assertIn("allow_all", inputs)
        self.assertIn("max_devices", inputs)
        description = inputs["filters"].description
        self.assertIn(".*", description)
        self.assertIn("case-sensitive", description.lower())
