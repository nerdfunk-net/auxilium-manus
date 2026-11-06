"""get-aci-details is registered consistently (registry, dispatch table, config)."""

from __future__ import annotations

import unittest
from pathlib import Path

from repositories.plugin_repository import PluginRepository
from services.execution.step_registry import STEP_REGISTRY
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from workflow_steps.get_aci_details.config import get_config
from workflow_steps.get_aci_details.executor import FACTS, execute

STEP_ID = "get-aci-details"
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "workflow_steps" / "registry.yaml"


class RegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        registry = PluginRegistryService(PluginRepository(REGISTRY_PATH)).load_registry()
        plugin = next((p for p in registry.plugins if p.id == STEP_ID), None)
        if plugin is None:
            raise AssertionError(f"{STEP_ID} is not in registry.yaml")
        cls.plugin = plugin

    def test_registry_entry_sits_in_the_cisco_configuration_slot(self) -> None:
        self.assertEqual(self.plugin.name, "Get Details from ACI")
        self.assertEqual(self.plugin.artifact_type, "configuration_management")
        self.assertEqual(self.plugin.palette_category, "cisco")
        self.assertEqual(self.plugin.directory, "get_aci_details")
        self.assertTrue(self.plugin.enabled)

    def test_capability_contract_matches_the_other_fact_steps(self) -> None:
        self.assertEqual(self.plugin.requires, ["identity"])
        self.assertEqual(self.plugin.produces, ["parsed"])
        self.assertEqual([o.name for o in self.plugin.outcomes], ["success", "failure"])

    def test_dispatch_table_points_at_the_executor(self) -> None:
        self.assertIs(STEP_REGISTRY[STEP_ID], execute)

    def test_documented_config_inputs_match_default_config_keys(self) -> None:
        documented = {item.name for item in self.plugin.metadata.configuration_input}
        self.assertEqual(documented, set(get_config()))

    def test_facts_input_documents_every_fact_and_the_default(self) -> None:
        inputs = {item.name: item for item in self.plugin.metadata.configuration_input}
        facts = inputs["facts"]
        self.assertTrue(facts.required)
        for fact in FACTS:
            self.assertIn(fact, facts.description, msg=fact)
        self.assertEqual(list(facts.default), list(get_config()["facts"]))

    def test_output_key_input_documents_the_default_and_the_path(self) -> None:
        inputs = {item.name: item for item in self.plugin.metadata.configuration_input}
        key = inputs["parsed_output_key"]
        self.assertEqual(key.default, get_config()["parsed_output_key"])
        self.assertIn("parsed.<parsed_output_key>.<fact>", key.description)

    def test_default_config_is_a_fresh_object_each_time(self) -> None:
        first = get_config()
        first["facts"].append("vpc")
        self.assertNotIn("vpc", get_config()["facts"])


if __name__ == "__main__":
    unittest.main()
