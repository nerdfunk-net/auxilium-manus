"""compare-aci-subnets: registration and executor (mocked service layer, no network)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from models.aci_subnets import AciSubnet
from models.workflow_context import (
    ArtifactRef,
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from repositories.plugin_repository import PluginRepository
from services.aci.common.exceptions import AciAPIError, AciValidationError
from services.aci.source_config_service import AciSourceNotFoundError
from services.artifacts import InMemoryArtifactService
from services.execution.step_registry import STEP_REGISTRY
from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.prefix_reader import NautobotPrefix
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from workflow_steps.compare_aci_subnets.config import get_config
from workflow_steps.compare_aci_subnets.executor import execute

STEP_ID = "compare-aci-subnets"
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "workflow_steps" / "registry.yaml"
EXEC = "workflow_steps.compare_aci_subnets.executor"

ACI = (
    AciSubnet(prefix="10.1.1.0/24", gateway="10.1.1.1", tenant="T", bridge_domain="BD1", vrf="V1"),
    AciSubnet(prefix="10.1.2.0/24", gateway="10.1.2.1", tenant="T", bridge_domain="BD2", vrf="V1"),
)
NAUTOBOT = (
    NautobotPrefix(prefix="10.1.1.0/24", namespace="Global", status="Active", type="network"),
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
        self.assertEqual(self.plugin.name, "Compare ACI Subnets with Nautobot")
        self.assertEqual(self.plugin.palette_category, "cisco")
        self.assertEqual(self.plugin.directory, "compare_aci_subnets")
        self.assertEqual(self.plugin.requires, [])
        self.assertEqual([o.name for o in self.plugin.outcomes], ["success", "differences"])
        self.assertTrue(self.plugin.enabled)

    def test_dispatch_and_documented_config(self) -> None:
        self.assertIs(STEP_REGISTRY[STEP_ID], execute)
        documented = {i.name: i for i in self.plugin.metadata.configuration_input}
        self.assertEqual(set(documented), set(get_config()))
        for key, value in get_config().items():
            if key in ("namespace", "output_key"):
                self.assertEqual(documented[key].default, value, msg=key)

    def test_the_report_is_documented(self) -> None:
        text = " ".join(i.description for i in self.plugin.metadata.configuration_input)
        for word in ("missing_in_nautobot", "missing_in_aci", "overlaps", "artifact"):
            self.assertIn(word, text)

    def test_default_config_is_a_fresh_object_each_time(self) -> None:
        first = get_config()
        first["scope_prefixes"].append("10.0.0.0/8")
        self.assertEqual(get_config()["scope_prefixes"], [])


class _Patched:
    def __init__(self, aci=ACI, nautobot=NAUTOBOT, aci_error=None, nautobot_error=None) -> None:
        self.subnets = MagicMock()
        self.subnets.list_subnets = AsyncMock(return_value=aci, side_effect=aci_error)
        self.reader = MagicMock()
        self.reader.list_prefixes = AsyncMock(return_value=nautobot, side_effect=nautobot_error)
        self.aci_source = MagicMock()

    def __enter__(self):
        self._patches = [
            patch(f"{EXEC}.object_session", return_value=MagicMock()),
            patch("service_factory.build_aci_source_config_service", return_value=self.aci_source),
            patch(f"{EXEC}.resolve_nautobot_credentials", return_value=MagicMock()),
            patch("service_factory.build_aci_subnet_service", return_value=self.subnets),
            patch("service_factory.build_nautobot_prefix_reader", return_value=self.reader),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


def _device() -> DeviceContext:
    return DeviceContext(
        id="d1",
        name="d1",
        hostname="d1",
        source="nautobot",
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


async def _run(config: dict | None = None, *, artifacts=None, devices=()):
    run = MagicMock()
    run.id = 1
    base = {"aci_source_id": "lab", "nautobot_source_id": "nb"}
    artifacts = artifacts or InMemoryArtifactService()
    outcomes = await execute(
        config={**base, **(config or {})},
        context=WorkflowContext(run_id="r", workflow_id="w", devices={d.id: d for d in devices}),
        run=run,
        artifact_service=artifacts,
        node_id="n1",
        device_sessions=MagicMock(),
    )
    return outcomes, artifacts


class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_drift_emits_success_and_differences_with_the_report_in_the_metadata(
        self,
    ) -> None:
        with _Patched():
            outcomes, _ = await _run()
        self.assertEqual([o.name for o in outcomes], ["success", "differences"])
        entry = outcomes[0].context.metadata["n1.aci_subnet_report"]
        self.assertEqual(entry["summary"]["missing_in_nautobot"], 1)
        self.assertEqual(entry["summary"]["matched"], 1)
        self.assertEqual(entry["missing_in_nautobot"], ["10.1.2.0/24"])
        self.assertEqual(outcomes[1].context.metadata, outcomes[0].context.metadata)

    async def test_in_sync_emits_only_success(self) -> None:
        with _Patched(aci=ACI[:1]):
            outcomes, _ = await _run()
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertFalse(
            outcomes[0].context.metadata["n1.aci_subnet_report"]["summary"]["differences"]
        )

    async def test_the_full_report_is_stored_as_a_json_artifact(self) -> None:
        with _Patched():
            outcomes, artifacts = await _run()
        entry = outcomes[0].context.metadata["n1.aci_subnet_report"]
        ref = ArtifactRef.model_validate(entry["artifact_ref"])
        report = json.loads(await artifacts.resolve(ref))
        self.assertEqual(report["missing_in_nautobot"][0]["prefix"], "10.1.2.0/24")
        self.assertEqual(ref.media_type, "application/json")

    async def test_the_metadata_samples_are_capped_but_the_summary_is_complete(self) -> None:
        many = tuple(
            AciSubnet(
                prefix=f"10.{i // 256}.{i % 256}.0/24", gateway="1.1.1.1", tenant="T", vrf="V"
            )
            for i in range(300)
        )
        with _Patched(aci=many, nautobot=()):
            outcomes, _ = await _run()
        entry = outcomes[0].context.metadata["n1.aci_subnet_report"]
        self.assertEqual(entry["summary"]["missing_in_nautobot"], 300)
        self.assertEqual(len(entry["missing_in_nautobot"]), 50)

    async def test_devices_pass_through_untouched(self) -> None:
        with _Patched():
            outcomes, _ = await _run(devices=(_device(),))
        self.assertEqual(list(outcomes[0].context.devices), ["d1"])
        self.assertEqual(outcomes[0].context.devices["d1"].status, DeviceStatus.OK)

    async def test_options_reach_the_comparison(self) -> None:
        nb = (
            NautobotPrefix(prefix="10.1.1.0/24", namespace="V1", status="Active", type="network"),
        )
        with _Patched(nautobot=nb):
            outcomes, _ = await _run(
                {"namespace_from_vrf": True, "scope_prefixes": ["10.1.0.0/16"]}
            )
        summary = outcomes[0].context.metadata["n1.aci_subnet_report"]["summary"]
        self.assertEqual(
            (summary["matched"], summary["missing_in_nautobot"], summary["missing_in_aci"]),
            (1, 1, 0),
        )

    async def test_blank_scope_lines_are_ignored(self) -> None:
        with _Patched():
            outcomes, _ = await _run({"scope_prefixes": ["", "  ", "10.1.0.0/16", "\t"]})
        summary = outcomes[0].context.metadata["n1.aci_subnet_report"]["summary"]
        self.assertEqual(summary["missing_in_aci"], 0)

    async def test_the_output_key_is_configurable(self) -> None:
        with _Patched():
            outcomes, _ = await _run({"output_key": "drift"})
        self.assertIn("n1.drift", outcomes[0].context.metadata)

    async def test_configuration_errors_raise_before_any_io(self) -> None:
        bad = (
            {"aci_source_id": ""},
            {"nautobot_source_id": " "},
            {"namespace": ""},
            {"output_key": "has space"},
            {"scope_prefixes": "10.0.0.0/8"},
            {"scope_prefixes": ["nonsense"]},
            {"scope_prefixes": [1]},
        )
        for config in bad:
            with self.subTest(config=config), _Patched() as p:
                with self.assertRaises(ValueError) as caught:
                    await _run(config)
                self.assertIn(STEP_ID, str(caught.exception))
                p.subnets.list_subnets.assert_not_awaited()

    async def test_an_unknown_aci_source_is_a_configuration_error(self) -> None:
        with _Patched() as p:
            p.aci_source.resolve_credentials.side_effect = AciSourceNotFoundError("nope")
            with self.assertRaisesRegex(ValueError, "not found"):
                await _run()

    async def test_an_apic_failure_fails_the_step_with_the_cause_kept(self) -> None:
        error = AciAPIError("apic down", code="transport")
        with _Patched(aci_error=error):
            with self.assertRaises(RuntimeError) as caught:
                await _run()
        self.assertIs(caught.exception.__cause__, error)
        self.assertIn(STEP_ID, str(caught.exception))

    async def test_a_nautobot_failure_fails_the_step_with_the_cause_kept(self) -> None:
        error = NautobotAPIError("nb down", code="transport")
        with _Patched(nautobot_error=error):
            with self.assertRaises(RuntimeError) as caught:
                await _run()
        self.assertIs(caught.exception.__cause__, error)

    async def test_a_rejected_apic_query_is_a_configuration_error(self) -> None:
        with _Patched(aci_error=AciValidationError("bad filter")):
            with self.assertRaises(ValueError):
                await _run()


if __name__ == "__main__":
    unittest.main()
