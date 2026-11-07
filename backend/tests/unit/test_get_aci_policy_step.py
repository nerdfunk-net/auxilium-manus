"""get-aci-policy: registration and executor (mocked service layer, no network)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from models.aci import AciDevice
from models.aci_facts import AciEpg
from models.aci_policy import AciL3OutNode, AciPolicyContract, AciPolicyEpg, AciPolicyL3Out
from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from repositories.plugin_repository import PluginRepository
from services.aci.common.exceptions import AciAPIError
from services.aci.policy_service import AciPolicySnapshot
from services.artifacts import InMemoryArtifactService
from services.execution.step_registry import STEP_REGISTRY
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from workflow_steps.common.device_builders import device_context_from_aci
from workflow_steps.get_aci_policy.config import get_config
from workflow_steps.get_aci_policy.executor import execute

STEP_ID = "get-aci-policy"
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "workflow_steps" / "registry.yaml"
FACTS_MODULE = "workflow_steps.common.aci_facts"
WEB = "uni/tn-Heroes/ap-App/epg-web"
DB = "uni/tn-Heroes/ap-App/epg-db"

SNAPSHOT = AciPolicySnapshot(
    epgs={
        WEB: AciPolicyEpg(
            epg_dn=WEB, tenant="Heroes", app_profile="App", epg="web", consumed=("Heroes/sql",)
        ),
        DB: AciPolicyEpg(
            epg_dn=DB, tenant="Heroes", app_profile="App", epg="db", provided=("Heroes/sql",)
        ),
    },
    l3outs={
        ("Heroes", "Internet"): AciPolicyL3Out(
            tenant="Heroes",
            name="Internet",
            nodes=(AciL3OutNode(pod_id=1, node_id=101),),
        )
    },
    contracts={
        ("Heroes", "sql"): AciPolicyContract(
            tenant="Heroes", name="sql", provider_epgs=(DB,), consumer_epgs=(WEB,)
        )
    },
)


class RegistrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        registry = PluginRegistryService(PluginRepository(REGISTRY_PATH)).load_registry()
        plugin = next((p for p in registry.plugins if p.id == STEP_ID), None)
        if plugin is None:
            raise AssertionError(f"{STEP_ID} is not in registry.yaml")
        cls.plugin = plugin

    def test_registry_entry(self) -> None:
        self.assertEqual(self.plugin.name, "Get Policy from ACI")
        self.assertEqual(self.plugin.palette_category, "cisco")
        self.assertEqual(self.plugin.directory, "get_aci_policy")
        self.assertEqual((self.plugin.requires, self.plugin.produces), (["identity"], ["parsed"]))
        self.assertEqual([o.name for o in self.plugin.outcomes], ["success", "failure"])
        self.assertTrue(self.plugin.enabled)

    def test_dispatch_and_documented_config(self) -> None:
        self.assertIs(STEP_REGISTRY[STEP_ID], execute)
        documented = {item.name for item in self.plugin.metadata.configuration_input}
        self.assertEqual(documented, set(get_config()))

    def test_output_key_documents_the_paths(self) -> None:
        key = {i.name: i for i in self.plugin.metadata.configuration_input}["parsed_output_key"]
        self.assertEqual(key.default, "aci_policy")
        self.assertIn("parsed.<parsed_output_key>.epgs.parsed", key.description)
        self.assertIn("parsed.<parsed_output_key>.contracts.parsed", key.description)
        self.assertIn("parsed.<parsed_output_key>.l3outs.parsed", key.description)


def _device(node_id: int, source_id: str = "lab") -> DeviceContext:
    return device_context_from_aci(
        AciDevice(node_id=node_id, name=f"leaf-{node_id}", role="leaf", pod_id=1),
        source_id=source_id,
    )


def _services(snapshot=SNAPSHOT, deployed=(AciEpg(epg_dn=WEB),)):
    policy = MagicMock()
    policy.snapshot = AsyncMock(
        side_effect=snapshot if isinstance(snapshot, Exception) else None,
        return_value=None if isinstance(snapshot, Exception) else snapshot,
    )
    details = MagicMock()
    details.get_epgs = AsyncMock(
        side_effect=deployed if isinstance(deployed, Exception) else None,
        return_value=None if isinstance(deployed, Exception) else deployed,
    )
    return policy, details


class _Patched:
    def __init__(self, policy: MagicMock, details: MagicMock) -> None:
        self.policy, self.details = policy, details
        self.source_config = MagicMock()
        self.policy_builder = MagicMock(return_value=policy)

    def __enter__(self):
        self._patches = [
            patch(f"{FACTS_MODULE}.object_session", return_value=MagicMock()),
            patch(
                "service_factory.build_aci_source_config_service", return_value=self.source_config
            ),
            patch("service_factory.build_aci_policy_service", self.policy_builder),
            patch("service_factory.build_aci_details_service", return_value=self.details),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


async def _run(config: dict, *devices: DeviceContext):
    run = MagicMock()
    run.id = 1
    return await execute(
        config=config,
        context=WorkflowContext(run_id="r", workflow_id="w", devices={d.id: d for d in devices}),
        run=run,
        artifact_service=InMemoryArtifactService(),
        node_id="n1",
        device_sessions=MagicMock(),
    )


class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_device_gets_its_deployed_epgs_and_their_contracts(self) -> None:
        with _Patched(*_services()):
            outcomes = await _run({}, _device(101))
        self.assertEqual([o.name for o in outcomes], ["success"])
        parsed = outcomes[0].context.devices["aci-lab-101"].parsed["aci_policy"]
        self.assertEqual([e["epg"] for e in parsed["epgs"]["parsed"]], ["web"])
        self.assertEqual(parsed["epgs"]["parsed"][0]["consumed"], ["Heroes/sql"])
        self.assertEqual([c["name"] for c in parsed["contracts"]["parsed"]], ["sql"])
        self.assertIsNone(parsed["epgs"]["error"])
        self.assertEqual([o["name"] for o in parsed["l3outs"]["parsed"]], ["Internet"])

    async def test_the_policy_is_read_once_per_source_for_all_devices(self) -> None:
        policy, details = _services()
        with _Patched(policy, details):
            await _run({}, _device(101), _device(102), _device(103, source_id="other"))
        self.assertEqual(policy.snapshot.await_count, 2)  # two sources, not three devices
        self.assertEqual(details.get_epgs.await_count, 3)

    async def test_each_device_asks_its_own_node(self) -> None:
        policy, details = _services()
        with _Patched(policy, details):
            await _run({}, _device(101), _device(102))
        self.assertEqual(
            sorted(c.args for c in details.get_epgs.await_args_list), [(1, 101), (1, 102)]
        )

    async def test_a_policy_failure_fails_every_device_with_the_error(self) -> None:
        with _Patched(*_services(snapshot=AciAPIError("apic down", code="transport"))):
            outcomes = await _run({}, _device(101))
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        failed = outcomes[1].context.devices["aci-lab-101"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertIn("apic down", failed.errors[-1].message)

    async def test_a_node_without_epgs_is_a_success_with_empty_lists(self) -> None:
        with _Patched(*_services(deployed=())):
            outcomes = await _run({}, _device(201))
        parsed = outcomes[0].context.devices["aci-lab-201"].parsed["aci_policy"]
        self.assertEqual(
            (parsed["epgs"]["parsed"], parsed["contracts"]["parsed"], parsed["l3outs"]["parsed"]),
            ([], [], []),
        )

    async def test_a_failure_reading_the_node_fails_that_device_only(self) -> None:
        policy, details = _services()
        details.get_epgs = AsyncMock(
            side_effect=[AciAPIError("node down", http_status=503), (AciEpg(epg_dn=WEB),)]
        )
        with _Patched(policy, details):
            outcomes = await _run({}, _device(101), _device(102))
        self.assertEqual(len(outcomes[0].context.devices), 1)
        self.assertEqual(len(outcomes[1].context.devices), 1)

    async def test_the_output_key_is_configurable_and_validated(self) -> None:
        with _Patched(*_services()):
            outcomes = await _run({"parsed_output_key": "pol"}, _device(101))
            self.assertIn("pol", outcomes[0].context.devices["aci-lab-101"].parsed)
            with self.assertRaises(ValueError):
                await _run({"parsed_output_key": "has space"}, _device(101))

    async def test_no_devices_is_a_no_op(self) -> None:
        with _Patched(*_services()) as p:
            outcomes = await _run({})
        self.assertEqual([o.name for o in outcomes], ["success"])
        p.policy.snapshot.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
