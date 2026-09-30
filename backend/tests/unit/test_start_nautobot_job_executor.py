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


class CoerceValueMultiObjectVarTests(unittest.TestCase):
    def test_single_uuid_is_wrapped_in_a_list(self) -> None:
        self.assertEqual(
            mod._coerce_value("devices", _UUID, "MultiObjectVar"),
            [_UUID],
        )

    def test_comma_separated_uuids_split_into_a_list(self) -> None:
        other = "660e8400-e29b-41d4-a716-446655440001"
        self.assertEqual(
            mod._coerce_value("devices", f"{_UUID}, {other}", "MultiObjectVar"),
            [_UUID, other],
        )

    def test_json_list_string_passes_through(self) -> None:
        self.assertEqual(
            mod._coerce_value("devices", f'["{_UUID}"]', "MultiObjectVar"),
            [_UUID],
        )

    def test_single_value_multichoicevar_is_wrapped_in_a_list(self) -> None:
        self.assertEqual(mod._coerce_value("roles", "core", "MultiChoiceVar"), ["core"])

    def test_single_value_jsonvar_is_not_wrapped(self) -> None:
        # JSONVar is not guaranteed list-valued, unlike MultiObjectVar/MultiChoiceVar.
        self.assertEqual(mod._coerce_value("payload", "solo", "JSONVar"), "solo")


class ParseConfigTests(unittest.TestCase):
    def test_parses_required_value_and_uuid_resolution(self) -> None:
        parsed = mod._parse_config(
            {
                "nautobot_source_id": "src-1",
                "job_id": "job-1",
                "job_variables_schema": [
                    {"name": "location", "required": True, "type": "ObjectVar"}
                ],
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
                value="a, b",
                uuid_resolution={"resource_type": "role", "content_type": "dcim.device"},
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


class ApplyJobResultRequestResponseTests(unittest.TestCase):
    def test_response_in_bag_and_request_in_requests(self) -> None:
        updated = mod._apply_job_result(
            _device(),
            job_result_id="jr-1",
            job_id="job-1",
            source_id="src-1",
            job_name="My Job",
            node_id="n",
            request={"data": {"location": _UUID}},
            response={"job_result": {"id": "jr-1"}},
        )
        bag = updated.attribute_bags["nautobot_job"]
        self.assertEqual(bag["response"], {"job_result": {"id": "jr-1"}})
        self.assertNotIn("request", bag)
        (record,) = updated.requests["n"]
        self.assertEqual(record.request, {"data": {"location": _UUID}})
        self.assertEqual(record.endpoint, "/api/extras/jobs/job-1/run/")
        self.assertIsNone(record.response)
        self.assertTrue(record.ok)

    def test_custom_bag_name_keeps_other_job_bags_independent(self) -> None:
        device = _device(onboard_job={"job_result_id": "jr-onboard"})
        updated = mod._apply_job_result(
            device,
            job_result_id="jr-update",
            job_id="job-2",
            source_id="src-1",
            job_name="Update Job",
            node_id="n",
            request={"data": {"location": _UUID}},
            response={"job_result": {"id": "jr-update"}},
            bag_name="update_job",
        )
        self.assertEqual(
            updated.attribute_bags["onboard_job"]["job_result_id"], "jr-onboard"
        )
        self.assertEqual(
            updated.attribute_bags["update_job"]["job_result_id"], "jr-update"
        )

    def test_secret_like_request_key_is_redacted(self) -> None:
        updated = mod._apply_job_result(
            _device(),
            job_result_id="jr-1",
            job_id="job-1",
            source_id="src-1",
            job_name="My Job",
            node_id="n",
            request={"data": {"api_key": "sk-supersecret", "location": "loc-1"}},
            response=None,
        )
        request = updated.requests["n"][0].request
        self.assertEqual(request["data"]["api_key"], "***REDACTED***")
        self.assertEqual(request["data"]["location"], "loc-1")


class FailDeviceRequestResponseTests(unittest.TestCase):
    def test_no_request_or_response_adds_nothing(self) -> None:
        _, failed = mod._fail_device(
            device_key="d1", device=_device(), node_id="n", exc=ValueError("bad")
        )
        self.assertNotIn("nautobot_job", failed.attribute_bags)
        self.assertEqual(failed.requests, {})

    def test_request_only_goes_to_requests_not_bag(self) -> None:
        _, failed = mod._fail_device(
            device_key="d1",
            device=_device(),
            node_id="n",
            exc=ValueError("bad"),
            job_id="job-1",
            request={"data": {"location": "NYC-DC1"}},
        )
        self.assertNotIn("nautobot_job", failed.attribute_bags)
        (record,) = failed.requests["n"]
        self.assertEqual(record.request, {"data": {"location": "NYC-DC1"}})
        self.assertFalse(record.ok)

    def test_response_on_failure_stays_in_bag(self) -> None:
        _, failed = mod._fail_device(
            device_key="d1",
            device=_device(),
            node_id="n",
            exc=ValueError("bad"),
            response={"detail": "nope"},
        )
        self.assertEqual(failed.attribute_bags["nautobot_job"], {"response": {"detail": "nope"}})

    def test_secret_like_key_redacted_on_failure(self) -> None:
        _, failed = mod._fail_device(
            device_key="d1",
            device=_device(),
            node_id="n",
            exc=ValueError("bad"),
            request={"data": {"password": "hunter2"}},
        )
        redacted = failed.requests["n"][0].request["data"]["password"]
        self.assertEqual(redacted, "***REDACTED***")


class StartJobForDeviceRequestResponseIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def _parsed(self):
        return mod._parse_config(
            {
                "nautobot_source_id": "src-1",
                "job_id": "job-1",
                "parameters": {
                    "required": {"location": {"value": "NYC-DC1"}},
                    "optional": {},
                },
            }
        )

    async def _start(self, jobs_service):
        return await mod._start_job_for_device(
            device_key="d1",
            device=_device("d1"),
            node_id="n",
            jobs_service=jobs_service,
            parsed=self._parsed(),
            variable_types={"location": "StringVar"},
            device_common="common-stub",
            run_id=None,
        )

    async def test_success_splits_response_and_request(self) -> None:
        jobs_service = AsyncMock()
        jobs_service.run_job = AsyncMock(return_value={"job_result": {"id": "jr-1"}})
        _, updated, ok = await self._start(jobs_service)
        self.assertTrue(ok)
        bag = updated.attribute_bags["nautobot_job"]
        self.assertEqual(bag["response"], {"job_result": {"id": "jr-1"}})
        self.assertNotIn("request", bag)
        self.assertEqual(
            updated.requests["n"][0].request, {"data": {"location": "NYC-DC1"}}
        )

    async def test_rest_call_failure_still_records_request(self) -> None:
        from services.nautobot.common.exceptions import NautobotAPIError

        jobs_service = AsyncMock()
        jobs_service.run_job = AsyncMock(side_effect=NautobotAPIError("boom"))
        _, failed, ok = await self._start(jobs_service)
        self.assertFalse(ok)
        self.assertNotIn("nautobot_job", failed.attribute_bags)
        record = failed.requests["n"][0]
        self.assertEqual(record.request, {"data": {"location": "NYC-DC1"}})
        self.assertFalse(record.ok)


if __name__ == "__main__":
    unittest.main()
