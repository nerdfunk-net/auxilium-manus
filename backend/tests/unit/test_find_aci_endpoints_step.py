"""find-aci-endpoints: registration and executor (mocked service layer, no network)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from models.aci_endpoint import AciEndpoint, AciEndpointAttachment
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from repositories.plugin_repository import PluginRepository
from services.aci.common.exceptions import AciAPIError, AciValidationError
from services.aci.source_config_service import AciSourceNotFoundError
from services.artifacts import InMemoryArtifactService
from services.execution.step_registry import STEP_REGISTRY
from services.plugin_registry.plugin_registry_service import PluginRegistryService
from workflow_steps.find_aci_endpoints.config import get_config
from workflow_steps.find_aci_endpoints.executor import execute

STEP_ID = "find-aci-endpoints"
REGISTRY_PATH = Path(__file__).resolve().parents[2] / "workflow_steps" / "registry.yaml"
FACTS_MODULE = "workflow_steps.common.aci_facts"
ENDPOINT = AciEndpoint(
    mac="00:50:56:AA:BB:01",
    ips=("10.1.1.5",),
    tenant="Heroes",
    app_profile="App",
    epg="web",
    attachments=(AciEndpointAttachment(pod_id=1, node_ids=(101,), interface="eth1/5"),),
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
        self.assertEqual(self.plugin.name, "Find Endpoint in ACI")
        self.assertEqual(self.plugin.palette_category, "cisco")
        self.assertEqual(self.plugin.directory, "find_aci_endpoints")
        self.assertEqual((self.plugin.requires, self.plugin.produces), (["identity"], ["parsed"]))
        self.assertEqual([o.name for o in self.plugin.outcomes], ["success", "failure"])
        self.assertTrue(self.plugin.enabled)

    def test_dispatch_and_documented_config(self) -> None:
        self.assertIs(STEP_REGISTRY[STEP_ID], execute)
        documented = {item.name for item in self.plugin.metadata.configuration_input}
        self.assertEqual(documented, set(get_config()))

    def test_the_documented_defaults_are_the_real_ones(self) -> None:
        inputs = {i.name: i for i in self.plugin.metadata.configuration_input}
        for key, value in get_config().items():
            self.assertEqual(inputs[key].default or "", value, msg=key)
        self.assertIn(
            "parsed.<parsed_output_key>.endpoints.parsed", inputs["parsed_output_key"].description
        )


def _device(
    device_id: str = "d1", *, ip: str | None = "10.1.1.5", source: str = "nautobot"
) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        source=source,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
        primary_ip4=ip,
    )


class _Patched:
    def __init__(self, find=None, resolve_side_effect=None) -> None:
        self.service = MagicMock()
        self.service.find = find or AsyncMock(return_value=(ENDPOINT,))
        self.source_config = MagicMock()
        if resolve_side_effect is not None:
            self.source_config.resolve_credentials.side_effect = resolve_side_effect
        self.builder = MagicMock(return_value=self.service)

    def __enter__(self):
        self._patches = [
            patch(f"{FACTS_MODULE}.object_session", return_value=MagicMock()),
            patch(
                "workflow_steps.find_aci_endpoints.executor.object_session",
                return_value=MagicMock(),
            ),
            patch(
                "service_factory.build_aci_source_config_service", return_value=self.source_config
            ),
            patch("service_factory.build_aci_endpoint_service", self.builder),
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
        config={"aci_source_id": "lab", **config},
        context=WorkflowContext(run_id="r", workflow_id="w", devices={d.id: d for d in devices}),
        run=run,
        artifact_service=InMemoryArtifactService(),
        node_id="n1",
        device_sessions=MagicMock(),
    )


class ExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_device_from_any_source_gets_where_its_ip_lives(self) -> None:
        with _Patched() as p:
            outcomes = await _run({}, _device())
        self.assertEqual([o.name for o in outcomes], ["success"])
        parsed = outcomes[0].context.devices["d1"].parsed["aci_endpoint"]["endpoints"]
        self.assertIsNone(parsed["error"])
        (endpoint,) = parsed["parsed"]
        self.assertEqual((endpoint["mac"], endpoint["epg"]), ("00:50:56:AA:BB:01", "web"))
        self.assertEqual(endpoint["attachments"][0]["interface"], "eth1/5")
        p.service.find.assert_awaited_once_with("10.1.1.5")

    async def test_an_address_the_fabric_does_not_know_is_a_success_with_an_empty_list(
        self,
    ) -> None:
        with _Patched(find=AsyncMock(return_value=())):
            outcomes = await _run({}, _device())
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertEqual(
            outcomes[0].context.devices["d1"].parsed["aci_endpoint"]["endpoints"]["parsed"], []
        )

    async def test_the_address_comes_from_the_configured_path(self) -> None:
        device = _device(ip=None).model_copy(
            update={"attribute_bags": {"custom": {"mac": "0050.56aa.bb01"}}}
        )
        with _Patched() as p:
            outcomes = await _run({"address_path": "custom.mac"}, device)
        self.assertEqual([o.name for o in outcomes], ["success"])
        p.service.find.assert_awaited_once_with("0050.56aa.bb01")

    async def test_a_sealed_secret_is_never_decrypted_into_the_apic_query(self) -> None:
        from core.crypto import EncryptionService
        from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER, seal_secret

        sealed = seal_secret("10.9.9.9", encryption=EncryptionService("test-secret-key-find-aci"))
        device = _device(ip=None).model_copy(
            update={"attribute_bags": {"custom": {"address": sealed}}}
        )
        # Make decryption work, so only the reveal_secrets switch decides whether it is used.
        with (
            patch(
                "services.workflow_context.attribute_path.unwrap_secret", return_value="10.9.9.9"
            ) as unwrap,
            _Patched() as p,
        ):
            await _run({"address_path": "custom.address"}, device)
        # The service gets the placeholder (it rejects it before any request), never the value.
        p.service.find.assert_awaited_once_with(REDACTED_PLACEHOLDER)
        unwrap.assert_not_called()

    async def test_a_device_without_an_address_fails_with_a_code(self) -> None:
        with _Patched() as p:
            outcomes = await _run({}, _device(ip=None), _device("d2"))
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        failed = outcomes[1].context.devices["d1"]
        self.assertEqual(failed.errors[-1].code, "no_address")
        p.service.find.assert_awaited_once()  # only the device with an address is looked up

    async def test_an_apic_failure_fails_that_device_with_the_error(self) -> None:
        find = AsyncMock(side_effect=AciAPIError("apic down", code="transport"))
        with _Patched(find=find):
            outcomes = await _run({}, _device())
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        self.assertIn("apic down", outcomes[1].context.devices["d1"].errors[-1].message)

    async def test_a_value_that_is_not_an_address_fails_without_echoing_it(self) -> None:
        find = AsyncMock(side_effect=AciValidationError("Not an IPv4 or MAC address"))
        with _Patched(find=find):
            outcomes = await _run({}, _device(ip="leaf-1"))
        message = outcomes[1].context.devices["d1"].errors[-1].message
        self.assertIn("Not an IPv4 or MAC address", message)
        self.assertNotIn("leaf-1", message)

    async def test_configuration_errors_raise_before_any_io(self) -> None:
        for config in (
            {"aci_source_id": ""},
            {"parsed_output_key": "has space"},
            {"address_path": "  "},
        ):
            with self.subTest(config=config), _Patched() as p:
                with self.assertRaises(ValueError) as caught:
                    await _run(
                        config, _device()
                    ) if "aci_source_id" not in config else await execute(
                        config=config,
                        context=WorkflowContext(
                            run_id="r", workflow_id="w", devices={"d1": _device()}
                        ),
                        run=MagicMock(),
                        artifact_service=InMemoryArtifactService(),
                        node_id="n1",
                        device_sessions=MagicMock(),
                    )
                self.assertIn(STEP_ID, str(caught.exception))
                p.source_config.resolve_credentials.assert_not_called()

    async def test_an_unknown_source_is_a_configuration_error(self) -> None:
        with _Patched(resolve_side_effect=AciSourceNotFoundError("nope")):
            with self.assertRaisesRegex(ValueError, "not found"):
                await _run({}, _device())

    async def test_no_devices_is_a_no_op(self) -> None:
        with _Patched() as p:
            outcomes = await _run({})
        self.assertEqual([o.name for o in outcomes], ["success"])
        p.service.find.assert_not_awaited()

    async def test_several_devices_are_looked_up_each_by_its_own_address(self) -> None:
        with _Patched() as p:
            await _run({}, _device("a", ip="10.1.1.5"), _device("b", ip="10.1.1.6"))
        self.assertEqual(
            sorted(c.args[0] for c in p.service.find.await_args_list), ["10.1.1.5", "10.1.1.6"]
        )


if __name__ == "__main__":
    unittest.main()
