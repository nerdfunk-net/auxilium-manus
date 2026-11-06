"""get-aci-devices is registered consistently (registry, dispatch table, config)."""

from __future__ import annotations

import unittest
from pathlib import Path

from repositories.plugin_repository import PluginRepository
from services.execution.step_registry import STEP_REGISTRY
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from workflow_steps.get_aci_devices.config import get_config
from workflow_steps.get_aci_devices.executor import execute

STEP_ID = "get-aci-devices"
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "workflow_steps" / "registry.yaml"


class RegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        registry = PluginRegistryService(PluginRepository(REGISTRY_PATH)).load_registry()
        plugin = next((p for p in registry.plugins if p.id == STEP_ID), None)
        if plugin is None:
            raise AssertionError(f"{STEP_ID} is not in registry.yaml")
        cls.plugin = plugin

    def test_registry_entry_exists_in_the_cisco_inventory_slot(self) -> None:
        self.assertEqual(self.plugin.name, "Get from ACI")
        self.assertEqual(self.plugin.artifact_type, "inventory_selector")
        self.assertEqual(self.plugin.palette_category, "cisco")
        self.assertEqual(self.plugin.directory, "get_aci_devices")
        self.assertTrue(self.plugin.enabled)

    def test_capability_contract_matches_other_inventory_steps(self) -> None:
        self.assertEqual(self.plugin.requires, [])
        self.assertEqual(self.plugin.produces, ["identity"])
        self.assertEqual([o.name for o in self.plugin.outcomes], ["success"])

    def test_dispatch_table_points_at_the_executor(self) -> None:
        self.assertIs(STEP_REGISTRY[STEP_ID], execute)

    def test_documented_config_inputs_match_default_config_keys(self) -> None:
        documented = {item.name for item in self.plugin.metadata.configuration_input}
        self.assertEqual(documented, set(get_config()))

    def test_source_and_guard_inputs_are_described(self) -> None:
        inputs = {item.name: item for item in self.plugin.metadata.configuration_input}
        self.assertTrue(inputs["aci_source_id"].required)
        self.assertIn("allow_all", inputs)
        self.assertIn("max_devices", inputs)

    def test_filter_help_documents_the_real_semantics(self) -> None:
        description = {i.name: i for i in self.plugin.metadata.configuration_input}[
            "filters"
        ].description
        for text in ("names", "roles", "pod_ids", "node_ids", "cidr", "case-sensitive", "*", "?"):
            self.assertIn(text, description)
        # Catalyst's dialect is ".*"; ACI's is "*" and "?" - the help must not mix them up.
        self.assertNotIn(".*", description)

    def test_default_config_has_no_filters_and_the_guard_on(self) -> None:
        config = get_config()
        self.assertEqual(config["filters"], {})
        self.assertIs(config["allow_all"], False)
        self.assertIsNone(config["max_devices"])
        self.assertIs(config["fan_out"]["enabled"], False)

    def test_default_config_is_a_fresh_object_each_time(self) -> None:
        first = get_config()
        first["filters"]["names"] = ["x"]
        self.assertEqual(get_config()["filters"], {})


if __name__ == "__main__":
    unittest.main()
