"""Unit tests for workflow_steps/start_nautobot_job/executor.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from models.workflow_context import DeviceContext
from workflow_steps.start_nautobot_job import executor as mod

_UUID = "550e8400-e29b-41d4-a716-446655440000"


def _device(did: str = "d1", **bags: object) -> DeviceContext:
    return DeviceContext(
        id=did, name=did, hostname=did, primary_ip4="10.0.0.1", attribute_bags=bags
    )


class SplitMultiValueTests(unittest.TestCase):
    def test_json_list(self) -> None:
        self.assertEqual(mod._split_multi_value('["a", "b"]'), ["a", "b"])

    def test_comma_separated(self) -> None:
        self.assertEqual(mod._split_multi_value("a, b ,c"), ["a", "b", "c"])

    def test_bad_json_returns_none(self) -> None:
        self.assertIsNone(mod._split_multi_value("[not json"))

    def test_single_value_returns_none(self) -> None:
        self.assertIsNone(mod._split_multi_value("solo"))


class ParseConfigTests(unittest.TestCase):
    def test_parses_required_value_and_uuid_resolution(self) -> None:
        parsed = mod._parse_config(
            {
                "nautobot_source_id": "src-1",
                "job_id": "job-1",
                "job_variables_schema": [{"name": "location", "required": True, "type": "ObjectVar"}],
                "parameters": {
                    "required": {
                        "location": {
                            "value": "NYC-DC1",
                            "uuid_resolution": {"resource_type": "location"},
                        }
                    },
                    "optional": {},
                },
            }
        )
        spec = parsed.required_params["location"]
        self.assertEqual(spec.value, "NYC-DC1")
        self.assertEqual(spec.uuid_resolution, {"resource_type": "location"})

    def test_optional_carries_enabled_value_and_uuid_resolution(self) -> None:
        parsed = mod._parse_config(
            {
                "nautobot_source_id": "src-1",
                "job_id": "job-1",
                "parameters": {
                    "required": {},
                    "optional": {
                        "role": {
                            "enabled": True,
                            "value": "core-router",
                            "uuid_resolution": {
                                "resource_type": "role",
                                "content_type": "dcim.interface",
                            },
                        }
                    },
                },
            }
        )
        enabled, spec = parsed.optional_params["role"]
        self.assertTrue(enabled)
        self.assertEqual(spec.value, "core-router")
        self.assertEqual(
            spec.uuid_resolution, {"resource_type": "role", "content_type": "dcim.interface"}
        )

    def test_unknown_resource_type_is_dropped(self) -> None:
        parsed = mod._parse_config(
            {
                "nautobot_source_id": "src-1",
                "job_id": "job-1",
                "parameters": {
                    "required": {
                        "x": {"value": "y", "uuid_resolution": {"resource_type": "vlan"}}
                    },
                    "optional": {},
                },
            }
        )
        self.assertIsNone(parsed.required_params["x"].uuid_resolution)

    def test_missing_required_param_raises(self) -> None:
        with self.assertRaises(ValueError):
            mod._parse_config(
                {
                    "nautobot_source_id": "src-1",
                    "job_id": "job-1",
                    "job_variables_schema": [{"name": "location", "required": True}],
                    "parameters": {"required": {}, "optional": {}},
                }
            )


class ResolveDeviceParamsUuidTests(unittest.IsolatedAsyncioTestCase):
    async def test_required_objectvar_resolves_to_uuid(self) -> None:
        required = {
            "location": mod._ParamSpec(
                value="NYC-DC1", uuid_resolution={"resource_type": "location"}
            )
        }
        with patch.object(mod, "resolve_nautobot_uuid", AsyncMock(return_value=_UUID)) as resolve:
            data = await mod._resolve_device_params(
                device=_device(),
                required_params=required,
                optional_params={},
                variable_types={"location": "ObjectVar"},
                device_common="common-stub",
                run_id=None,
            )
        self.assertEqual(data, {"location": _UUID})
        resolve.assert_awaited_once_with(
            "common-stub", "location", "NYC-DC1", content_type=None
        )

    async def test_multiobjectvar_resolves_each_item(self) -> None:
        required = {
            "roles": mod._ParamSpec(
                value="a, b", uuid_resolution={"resource_type": "role", "content_type": "dcim.device"}
            )
        }
        with patch.object(
            mod, "resolve_nautobot_uuid", AsyncMock(side_effect=["uuid-a", "uuid-b"])
        ) as resolve:
            data = await mod._resolve_device_params(
                device=_device(),
                required_params=required,
                optional_params={},
                variable_types={"roles": "MultiObjectVar"},
                device_common="common-stub",
                run_id=None,
            )
        self.assertEqual(data, {"roles": ["uuid-a", "uuid-b"]})
        self.assertEqual(resolve.await_count, 2)

    async def test_uuid_resolution_not_found_propagates_value_error(self) -> None:
        required = {
            "location": mod._ParamSpec(
                value="Nowhere", uuid_resolution={"resource_type": "location"}
            )
        }
        with patch.object(
            mod, "resolve_nautobot_uuid", AsyncMock(side_effect=ValueError("not found"))
        ):
            with self.assertRaises(ValueError):
                await mod._resolve_device_params(
                    device=_device(),
                    required_params=required,
                    optional_params={},
                    variable_types={"location": "ObjectVar"},
                    device_common="common-stub",
                    run_id=None,
                )

    async def test_non_uuid_param_still_uses_coerce_value(self) -> None:
        required = {"count": mod._ParamSpec(value="5", uuid_resolution=None)}
        data = await mod._resolve_device_params(
            device=_device(),
            required_params=required,
            optional_params={},
            variable_types={"count": "IntegerVar"},
            device_common="common-stub",
            run_id=None,
        )
        self.assertEqual(data, {"count": 5})

    async def test_disabled_optional_param_is_skipped_even_with_uuid_resolution(self) -> None:
        optional = {
            "location": (
                False,
                mod._ParamSpec(value="NYC-DC1", uuid_resolution={"resource_type": "location"}),
            )
        }
        with patch.object(mod, "resolve_nautobot_uuid", AsyncMock()) as resolve:
            data = await mod._resolve_device_params(
                device=_device(),
                required_params={},
                optional_params=optional,
                variable_types={"location": "ObjectVar"},
                device_common="common-stub",
                run_id=None,
            )
        self.assertEqual(data, {})
        resolve.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
