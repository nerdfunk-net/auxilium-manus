"""Tests for the add-nautobot-metadata executor (mocked service layer, no network)."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.nautobot.common.exceptions import NautobotAPIError
from services.nautobot.metadata_creation import (
    DeviceTypeResult,
    EnsureResult,
    MetadataReferenceNotFoundError,
)
from workflow_steps.add_nautobot_metadata.config import get_config
from workflow_steps.add_nautobot_metadata.executor import execute

_MODULE = "workflow_steps.add_nautobot_metadata.executor"

_LOCATION_CONFIG = {
    **get_config(),
    "nautobot_source_id": "prod-lab",
    "metadata_type": "location",
    "location": {
        "location_type": "{custom.location_type}",
        "name": "{custom.location_name}",
        "status": "Active",
        "description": "{custom.description}",
        "parent": "",
    },
}

_DEVICE_TYPE_CONFIG = {
    **get_config(),
    "nautobot_source_id": "prod-lab",
    "metadata_type": "device_type",
    "device_type": {
        "manufacturer": "{custom.manufacturer}",
        "role": "{custom.role}",
        "model": "{custom.model}",
        "height": "1",
        "platform": "{custom.platform}",
    },
}


def _device(device_id: str, custom: dict[str, Any] | None = None, **bags: Any) -> DeviceContext:
    attribute_bags: dict[str, dict[str, Any]] = {**bags}
    if custom is not None:
        attribute_bags["custom"] = custom
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        source="list",
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
        attribute_bags=attribute_bags,
    )


def _context(devices: dict[str, DeviceContext]) -> WorkflowContext:
    return WorkflowContext(run_id="run-uuid-1", workflow_id="wf-1", devices=devices)


def _service(**methods: AsyncMock) -> MagicMock:
    instance = MagicMock()
    for name, mock in methods.items():
        setattr(instance, name, mock)
    return instance


async def _run(
    config: dict[str, Any], devices: dict[str, DeviceContext], service: MagicMock
) -> list[StepOutcome]:
    run = MagicMock()
    run.id = 1
    with (
        patch(f"{_MODULE}.object_session", return_value=MagicMock()),
        patch(f"{_MODULE}.resolve_nautobot_credentials", return_value=MagicMock()),
        patch("service_factory.get_nautobot_app_service", return_value=MagicMock()),
        patch(f"{_MODULE}.CredentialsBoundNautobotClient", return_value=MagicMock()),
        patch(f"{_MODULE}.MetadataCreationService", return_value=service),
    ):
        return await execute(
            config=config,
            context=_context(devices),
            run=run,
            artifact_service=MagicMock(),
            node_id="node-1",
            device_sessions=MagicMock(),
        )


def _by_name(outcomes: list[StepOutcome]) -> dict[str, StepOutcome]:
    return {outcome.name: outcome for outcome in outcomes}


_LOCATION_CUSTOM = {
    "location_type": "Site",
    "location_name": "Berlin",
    "description": "HQ",
}
_DEVICE_TYPE_CUSTOM = {
    "manufacturer": "Cisco",
    "role": "Access Switch",
    "model": "C9300-24T",
    "platform": "cisco_ios",
}


class ConfigValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_source_id(self) -> None:
        with self.assertRaises(ValueError):
            await _run(
                {**_LOCATION_CONFIG, "nautobot_source_id": ""},
                {"d1": _device("d1", _LOCATION_CUSTOM)},
                _service(),
            )

    async def test_rejects_unknown_metadata_type(self) -> None:
        with self.assertRaises(ValueError):
            await _run(
                {**_LOCATION_CONFIG, "metadata_type": "rack"},
                {"d1": _device("d1", _LOCATION_CUSTOM)},
                _service(),
            )

    async def test_missing_metadata_type_defaults_to_location(self) -> None:
        ensure = AsyncMock(return_value=EnsureResult(id="l", name="Berlin", created=True))
        config = {k: v for k, v in _LOCATION_CONFIG.items() if k != "metadata_type"}
        await _run(
            config,
            {"d1": _device("d1", _LOCATION_CUSTOM)},
            _service(ensure_location=ensure),
        )
        ensure.assert_awaited_once()

    async def test_requires_devices(self) -> None:
        with self.assertRaises(ValueError):
            await _run(_LOCATION_CONFIG, {}, _service())


class LocationTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolves_attribute_bag_values_and_enriches_device(self) -> None:
        ensure = AsyncMock(return_value=EnsureResult(id="loc-1", name="Berlin", created=True))
        outcomes = await _run(
            _LOCATION_CONFIG,
            {"d1": _device("d1", _LOCATION_CUSTOM, nautobot={"serial": "ABC"})},
            _service(ensure_location=ensure),
        )

        ensure.assert_awaited_once_with(
            location_type="Site",
            name="Berlin",
            status="Active",
            description="HQ",
            parent=None,
        )
        result = _by_name(outcomes)["success"].context.devices["d1"]
        self.assertEqual(result.status, DeviceStatus.OK)
        self.assertIn(Capability.ATTRIBUTES, result.capabilities)
        # merged into, never replacing, the existing bag
        self.assertEqual(
            result.attribute_bags["nautobot"]["location"], {"name": "Berlin", "id": "loc-1"}
        )
        self.assertEqual(result.attribute_bags["nautobot"]["serial"], "ABC")
        self.assertNotIn("failure", _by_name(outcomes))

    async def test_blank_status_falls_back_to_active_and_description_may_be_empty(self) -> None:
        config = {
            **_LOCATION_CONFIG,
            "location": {
                "location_type": "Site",
                "name": "Berlin",
                "status": "",
                "description": "",
                "parent": "Region-1",
            },
        }
        ensure = AsyncMock(return_value=EnsureResult(id="loc-1", name="Berlin", created=False))
        await _run(config, {"d1": _device("d1")}, _service(ensure_location=ensure))

        ensure.assert_awaited_once_with(
            location_type="Site",
            name="Berlin",
            status="Active",
            description="",
            parent="Region-1",
        )

    async def test_unresolved_description_token_is_treated_as_empty(self) -> None:
        ensure = AsyncMock(return_value=EnsureResult(id="l", name="Berlin", created=True))
        custom = {k: v for k, v in _LOCATION_CUSTOM.items() if k != "description"}
        outcomes = await _run(
            _LOCATION_CONFIG, {"d1": _device("d1", custom)}, _service(ensure_location=ensure)
        )
        self.assertEqual(ensure.await_args.kwargs["description"], "")
        self.assertIn("success", _by_name(outcomes))
        self.assertNotIn("failure", _by_name(outcomes))

    async def test_status_can_come_from_an_attribute_bag(self) -> None:
        config = {
            **_LOCATION_CONFIG,
            "location": {**_LOCATION_CONFIG["location"], "status": "{nautobot.status}"},
        }
        ensure = AsyncMock(return_value=EnsureResult(id="l", name="Berlin", created=True))
        await _run(
            config,
            {"d1": _device("d1", _LOCATION_CUSTOM, nautobot={"status": "Planned"})},
            _service(ensure_location=ensure),
        )
        self.assertEqual(ensure.await_args.kwargs["status"], "Planned")

    async def test_unresolved_token_fails_device_without_calling_nautobot(self) -> None:
        ensure = AsyncMock()
        outcomes = await _run(
            _LOCATION_CONFIG,
            {"d1": _device("d1", {"location_type": "Site"})},
            _service(ensure_location=ensure),
        )

        ensure.assert_not_awaited()
        failed = _by_name(outcomes)["failure"].context.devices["d1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[0].code, "unresolved_attribute")
        self.assertIn("custom.location_name", failed.errors[0].message)

    async def test_blank_required_field_fails_device(self) -> None:
        ensure = AsyncMock()
        outcomes = await _run(
            _LOCATION_CONFIG,
            {"d1": _device("d1", {**_LOCATION_CUSTOM, "location_name": ""})},
            _service(ensure_location=ensure),
        )
        ensure.assert_not_awaited()
        failed = _by_name(outcomes)["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[0].code, "missing_required_field")

    async def test_devices_sharing_a_location_call_nautobot_once(self) -> None:
        ensure = AsyncMock(return_value=EnsureResult(id="loc-1", name="Berlin", created=True))
        devices = {f"d{n}": _device(f"d{n}", _LOCATION_CUSTOM) for n in range(3)}
        outcomes = await _run(_LOCATION_CONFIG, devices, _service(ensure_location=ensure))

        self.assertEqual(ensure.await_count, 1)
        self.assertEqual(len(_by_name(outcomes)["success"].context.devices), 3)

    async def test_description_and_case_differences_share_one_call(self) -> None:
        ensure = AsyncMock(return_value=EnsureResult(id="l", name="Berlin", created=True))
        devices = {
            "a": _device("a", {**_LOCATION_CUSTOM, "description": "one"}),
            "b": _device(
                "b", {**_LOCATION_CUSTOM, "location_name": "berlin", "description": "two"}
            ),
        }
        await _run(_LOCATION_CONFIG, devices, _service(ensure_location=ensure))
        self.assertEqual(ensure.await_count, 1)

    async def test_unknown_reference_routes_device_to_failure(self) -> None:
        ensure = AsyncMock(
            side_effect=MetadataReferenceNotFoundError("Location type 'Site' not found in Nautobot")
        )
        outcomes = await _run(
            _LOCATION_CONFIG,
            {"d1": _device("d1", _LOCATION_CUSTOM)},
            _service(ensure_location=ensure),
        )
        failed = _by_name(outcomes)["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[0].code, "reference_not_found")

    async def test_api_error_for_one_device_leaves_the_other_successful(self) -> None:
        async def ensure(**kwargs: Any) -> EnsureResult:
            if kwargs["name"] == "Bad":
                raise NautobotAPIError("500 boom")
            return EnsureResult(id="loc", name=kwargs["name"], created=True)

        outcomes = await _run(
            _LOCATION_CONFIG,
            {
                "ok": _device("ok", _LOCATION_CUSTOM),
                "bad": _device("bad", {**_LOCATION_CUSTOM, "location_name": "Bad"}),
            },
            _service(ensure_location=AsyncMock(side_effect=ensure)),
        )
        by_name = _by_name(outcomes)
        self.assertEqual(set(by_name["success"].context.devices), {"ok"})
        self.assertEqual(set(by_name["failure"].context.devices), {"bad"})


class DeviceTypeTests(unittest.IsolatedAsyncioTestCase):
    def _result(self, **overrides: Any) -> DeviceTypeResult:
        values: dict[str, Any] = {
            "id": "dt-1",
            "model": "C9300-24T",
            "created": True,
            "manufacturer": "Cisco",
            "role": "Access Switch",
            "platform": "cisco_ios",
            "role_id": "role-1",
            "platform_id": "plat-1",
        }
        return DeviceTypeResult(**{**values, **overrides})

    async def test_creates_device_type_and_carries_role_and_platform(self) -> None:
        ensure = AsyncMock(return_value=self._result())
        outcomes = await _run(
            _DEVICE_TYPE_CONFIG,
            {"d1": _device("d1", _DEVICE_TYPE_CUSTOM)},
            _service(ensure_device_type=ensure),
        )

        ensure.assert_awaited_once_with(
            manufacturer="Cisco",
            model="C9300-24T",
            height=1,
            role="Access Switch",
            platform="cisco_ios",
        )
        bag = _by_name(outcomes)["success"].context.devices["d1"].attribute_bags["nautobot"]
        self.assertEqual(bag["device_type"], {"model": "C9300-24T", "id": "dt-1"})
        self.assertEqual(bag["role"], {"name": "Access Switch", "id": "role-1"})
        self.assertEqual(bag["platform"], {"name": "cisco_ios", "id": "plat-1"})

    async def test_platform_is_optional(self) -> None:
        config = {
            **_DEVICE_TYPE_CONFIG,
            "device_type": {**_DEVICE_TYPE_CONFIG["device_type"], "platform": ""},
        }
        ensure = AsyncMock(return_value=self._result(platform=None))
        outcomes = await _run(
            config, {"d1": _device("d1", _DEVICE_TYPE_CUSTOM)}, _service(ensure_device_type=ensure)
        )

        self.assertIsNone(ensure.await_args.kwargs["platform"])
        bag = _by_name(outcomes)["success"].context.devices["d1"].attribute_bags["nautobot"]
        self.assertNotIn("platform", bag)

    async def test_height_may_come_from_an_attribute_bag(self) -> None:
        config = {
            **_DEVICE_TYPE_CONFIG,
            "device_type": {**_DEVICE_TYPE_CONFIG["device_type"], "height": "{custom.height}"},
        }
        ensure = AsyncMock(return_value=self._result())
        await _run(
            config,
            {"d1": _device("d1", {**_DEVICE_TYPE_CUSTOM, "height": "2"})},
            _service(ensure_device_type=ensure),
        )
        self.assertEqual(ensure.await_args.kwargs["height"], 2)

    async def test_invalid_height_fails_device(self) -> None:
        for bad in ("abc", "0", "-1", "1.5"):
            with self.subTest(height=bad):
                config = {
                    **_DEVICE_TYPE_CONFIG,
                    "device_type": {**_DEVICE_TYPE_CONFIG["device_type"], "height": bad},
                }
                ensure = AsyncMock()
                outcomes = await _run(
                    config,
                    {"d1": _device("d1", _DEVICE_TYPE_CUSTOM)},
                    _service(ensure_device_type=ensure),
                )
                ensure.assert_not_awaited()
                failed = _by_name(outcomes)["failure"].context.devices["d1"]
                self.assertEqual(failed.errors[0].code, "invalid_height")

    async def test_blank_height_defaults_to_one(self) -> None:
        config = {
            **_DEVICE_TYPE_CONFIG,
            "device_type": {**_DEVICE_TYPE_CONFIG["device_type"], "height": ""},
        }
        ensure = AsyncMock(return_value=self._result())
        await _run(
            config, {"d1": _device("d1", _DEVICE_TYPE_CUSTOM)}, _service(ensure_device_type=ensure)
        )
        self.assertEqual(ensure.await_args.kwargs["height"], 1)

    async def test_missing_required_field_fails_device(self) -> None:
        ensure = AsyncMock()
        outcomes = await _run(
            _DEVICE_TYPE_CONFIG,
            {"d1": _device("d1", {**_DEVICE_TYPE_CUSTOM, "role": ""})},
            _service(ensure_device_type=ensure),
        )
        ensure.assert_not_awaited()
        failed = _by_name(outcomes)["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[0].code, "missing_required_field")
        self.assertIn("role", failed.errors[0].message)


if __name__ == "__main__":
    unittest.main()
