"""Tests for workflow_steps/get_virtual_chassis/executor.py."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import DeviceStatus, WorkflowContext
from workflow_steps.get_virtual_chassis import executor as mod
from workflow_steps.get_virtual_chassis.executor import execute

# The sample payload from the Nautobot GraphQL console, plus the per-member fields the
# step additionally requests.
_PAYLOAD: dict[str, Any] = {
    "data": {
        "virtual_chassis": [
            {
                "id": "632a9d4b-8a3f-46dc-8c03-644815b9b56e",
                "name": "LAB.local.zz",
                "members": [
                    {
                        "id": "360889df-735f-4663-8cbd-b731a6975eaa",
                        "name": "LAB.local.zz",
                        "vc_position": 1,
                        "vc_priority": 15,
                        "serial": "SN1",
                        "device_type": {"model": "C9300-48P"},
                        "platform": {"name": "Cisco IOS-XE", "network_driver": "cisco_xe"},
                        "primary_ip4": {"address": "10.0.0.1/24"},
                        "vc_master_for": {"id": "632a9d4b", "name": "LAB.local.zz"},
                    },
                    {
                        "id": "75eb94cb-28b9-4cd0-b853-025566a61f85",
                        "name": "LAB:2.local.zz",
                        "vc_position": 2,
                        "vc_priority": 1,
                        "serial": "SN2",
                        "device_type": {"model": "C9300-24P"},
                        "platform": None,
                        "primary_ip4": None,
                        "vc_master_for": None,
                    },
                ],
            }
        ]
    }
}


def _context() -> WorkflowContext:
    return WorkflowContext(run_id="r1", workflow_id="w1")


def _run() -> MagicMock:
    run = MagicMock()
    run.id = "r1"
    return run


async def _run_execute(
    config: dict[str, Any], payload: dict[str, Any] | None = None
) -> tuple[list[Any], AsyncMock]:
    service = MagicMock()
    service.graphql_query = AsyncMock(return_value=payload if payload is not None else _PAYLOAD)
    with (
        patch.object(mod, "object_session", return_value=MagicMock()),
        patch.object(mod, "resolve_nautobot_credentials", return_value=MagicMock()),
        patch.object(mod.service_factory, "get_nautobot_app_service", return_value=service),
    ):
        outcomes = await execute(
            config={"nautobot_source_id": "src", **config},
            context=_context(),
            run=_run(),
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )
    return outcomes, service.graphql_query


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_source_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "nautobot_source_id"):
            await execute(
                config={},
                context=_context(),
                run=_run(),
                artifact_service=MagicMock(),
                node_id="n1",
                device_sessions=MagicMock(),
            )

    async def test_invalid_config_raises_before_any_io(self) -> None:
        with self.assertRaisesRegex(ValueError, "index_regex"):
            await _run_execute({"index_regex": "("})

    async def test_unsplit_returns_one_device_per_stack(self) -> None:
        outcomes, _ = await _run_execute({})
        self.assertEqual([o.name for o in outcomes], ["success"])
        devices = outcomes[0].context.devices
        self.assertEqual(len(devices), 1)
        device = next(iter(devices.values()))
        self.assertEqual(device.name, "LAB.local.zz")
        self.assertEqual(device.primary_ip4, "10.0.0.1/24")
        self.assertEqual(outcomes[0].summary, "found 1 virtual chassis, 1 device(s)")

    async def test_split_returns_members_with_index(self) -> None:
        outcomes, _ = await _run_execute({"split_members": True})
        devices = outcomes[0].context.devices
        by_name = {d.name: d for d in devices.values()}
        self.assertEqual(set(by_name), {"LAB.local.zz", "LAB:2.local.zz"})
        self.assertEqual(
            by_name["LAB.local.zz"].attribute_bags["virtual_chassis"]["stack_index"], 0
        )
        self.assertEqual(
            by_name["LAB:2.local.zz"].attribute_bags["virtual_chassis"]["stack_index"], 1
        )
        self.assertEqual({d.primary_ip4 for d in by_name.values()}, {"10.0.0.1/24"})

    async def test_exact_filter_is_sent_to_graphql(self) -> None:
        _, query = await _run_execute({"name_filter": "LAB.local.zz"})
        self.assertEqual(query.await_args.args[1], {"name": ["LAB.local.zz"]})

    async def test_no_filter_sends_no_name_variable(self) -> None:
        _, query = await _run_execute({})
        self.assertEqual(query.await_args.args[1], {})

    async def test_contains_filter_is_applied_in_python(self) -> None:
        outcomes, query = await _run_execute({"name_match": "contains", "name_filter": "nomatch"})
        self.assertEqual(query.await_args.args[1], {})
        self.assertEqual(outcomes[0].context.devices, {})
        self.assertEqual(outcomes[0].summary, "found 0 virtual chassis, 0 device(s)")

    async def test_stack_without_master_ip_goes_to_failure(self) -> None:
        payload = {"data": {"virtual_chassis": [{**_PAYLOAD["data"]["virtual_chassis"][0]}]}}
        members = [dict(m) for m in payload["data"]["virtual_chassis"][0]["members"]]
        members[0] = {**members[0], "primary_ip4": None}
        payload["data"]["virtual_chassis"][0]["members"] = members

        outcomes, _ = await _run_execute({}, payload)
        self.assertEqual([o.name for o in outcomes], ["success", "failure"])
        self.assertEqual(outcomes[0].context.devices, {})
        failed = next(iter(outcomes[1].context.devices.values()))
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[0].code, "no_primary_ip")

    async def test_graphql_errors_raise_runtime_error(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "GraphQL"):
            await _run_execute({}, {"errors": [{"message": "boom"}]})

    async def test_fan_out_metadata_is_emitted_when_enabled(self) -> None:
        outcomes, _ = await _run_execute(
            {"fan_out": {"enabled": True, "mode": "per_device", "chunk_size": 1}}
        )
        fan_out = outcomes[0].context.metadata["_fan_out"]
        self.assertTrue(fan_out["enabled"])
        self.assertEqual(fan_out["inventory_node_id"], "n1")

    async def test_no_fan_out_metadata_by_default(self) -> None:
        outcomes, _ = await _run_execute({})
        self.assertNotIn("_fan_out", outcomes[0].context.metadata)


if __name__ == "__main__":
    unittest.main()
