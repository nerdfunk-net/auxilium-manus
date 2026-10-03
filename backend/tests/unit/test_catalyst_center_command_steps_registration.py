"""The Catalyst Center command/config steps are registered consistently."""

from __future__ import annotations

import unittest
from pathlib import Path

from repositories.plugin_repository import PluginRepository
from services.execution.step_registry import STEP_REGISTRY
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from workflow_steps.get_catalyst_center_configs.config import get_config as configs_config
from workflow_steps.get_catalyst_center_configs.executor import execute as configs_execute
from workflow_steps.get_catalyst_center_details.config import get_config as details_config
from workflow_steps.get_catalyst_center_details.executor import execute as details_execute
from workflow_steps.get_catalyst_center_health.config import get_config as health_config
from workflow_steps.get_catalyst_center_health.executor import execute as health_execute
from workflow_steps.get_catalyst_center_topology.config import get_config as topology_config
from workflow_steps.get_catalyst_center_topology.executor import execute as topology_execute
from workflow_steps.run_catalyst_center_command.config import get_config as command_config
from workflow_steps.run_catalyst_center_command.executor import execute as command_execute

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "workflow_steps" / "registry.yaml"

CASES = (
    ("run-catalyst-center-command", "run_catalyst_center_command", command_execute, command_config),
    ("get-catalyst-center-configs", "get_catalyst_center_configs", configs_execute, configs_config),
    ("get-catalyst-center-details", "get_catalyst_center_details", details_execute, details_config),
    (
        "get-catalyst-center-topology",
        "get_catalyst_center_topology",
        topology_execute,
        topology_config,
    ),
    ("get-catalyst-center-health", "get_catalyst_center_health", health_execute, health_config),
)


class RegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        registry = PluginRegistryService(PluginRepository(REGISTRY_PATH)).load_registry()
        cls.plugins = {p.id: p for p in registry.plugins}

    def test_each_step_is_registered_dispatched_and_documented(self) -> None:
        for step_id, directory, execute, get_config in CASES:
            with self.subTest(step=step_id):
                plugin = self.plugins[step_id]
                self.assertEqual(plugin.directory, directory)
                self.assertEqual(plugin.palette_category, "cisco")
                self.assertTrue(plugin.enabled)
                self.assertEqual(plugin.requires, ["identity"])
                self.assertEqual([o.name for o in plugin.outcomes], ["success", "failure"])
                self.assertIs(STEP_REGISTRY[step_id], execute)
                documented = {i.name for i in plugin.metadata.configuration_input}
                self.assertEqual(documented, set(get_config()))

    def test_capabilities_produced(self) -> None:
        self.assertEqual(self.plugins["get-catalyst-center-configs"].produces, ["running_config"])
        self.assertEqual(self.plugins["run-catalyst-center-command"].produces, ["parsed"])
        for step_id in (
            "get-catalyst-center-details",
            "get-catalyst-center-topology",
            "get-catalyst-center-health",
        ):
            self.assertEqual(self.plugins[step_id].produces, ["parsed"])
