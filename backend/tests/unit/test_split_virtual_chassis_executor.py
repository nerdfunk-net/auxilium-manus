"""Tests for workflow_steps/split_virtual_chassis (executor + pure split helpers)."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import MagicMock

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.workflow_context.attribute_path import resolve_device_attribute
from workflow_steps.get_virtual_chassis.stack import (
    StackSettings,
    build_stack_devices,
    parse_settings,
)
from workflow_steps.split_virtual_chassis.executor import execute
from workflow_steps.split_virtual_chassis.members import parse_settings as parse_split_settings
from workflow_steps.split_virtual_chassis.members import split_stack_device

_MASTER_ID = "360889df-735f-4663-8cbd-b731a6975eaa"
_MEMBER2_ID = "75eb94cb-28b9-4cd0-b853-025566a61f85"

# Real (sanitised) parsed output of a 2-member WS-C3850 stack, TextFSM parser.
_SHOW_VERSION = [
    {
        "hostname": "LAB.local.zz",
        "hardware": ["WS-C3850-48T", "WS-C3850-12S"],
        "serial": ["serial1", "serial2"],
        "mac_address": ["aaaa.bbbb.cccc", "a1a1.b1b1.c1c1"],
    }
]
_SHOW_SWITCH_DETAIL = [
    {"switch": "1", "role": "Active", "mac_address": "aaaa.bbbb.cccc", "state": "Ready"},
    {"switch": "2", "role": "Standby", "mac_address": "a1a1.b1b1.c1c1", "state": "Ready"},
]


def _vc() -> dict[str, Any]:
    def member(name: str, member_id: str, position: int, *, master: bool) -> dict[str, Any]:
        return {
            "id": member_id,
            "name": name,
            "vc_position": position,
            "vc_priority": 10 if master else 1,
            "serial": "old",
            "device_type": {"model": "WS-C3850-48T"},
            "platform": {"name": "Cisco IOS-XE", "network_driver": "cisco_xe"},
            "primary_ip4": {"address": "10.0.0.1/24"} if master else None,
            "vc_master_for": {"id": "vc-1", "name": "LAB.local.zz"} if master else None,
        }

    return {
        "id": "vc-1",
        "name": "LAB.local.zz",
        "members": [
            member("LAB.local.zz", _MASTER_ID, 1, master=True),
            member("LAB:2.local.zz", _MEMBER2_ID, 2, master=False),
        ],
    }


def _stack_device(*, with_parsed: bool = True) -> DeviceContext:
    """The unsplit device get-virtual-chassis produces, after run-command."""
    settings: StackSettings = parse_settings({})
    (device,) = build_stack_devices(_vc(), settings, source_id="src", node_id="n0")
    if not with_parsed:
        return device
    return device.model_copy(
        update={
            "parsed": {
                "parsed": {
                    "show version": {"parsed": _SHOW_VERSION, "error": None},
                    "show switch detail": {"parsed": _SHOW_SWITCH_DETAIL, "error": None},
                }
            },
            "capabilities": {Capability.IDENTITY, Capability.PARSED},
        }
    )


def _context(*devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(
        run_id="r1", workflow_id="w1", devices={d.id: d for d in devices}, metadata={"keep": 1}
    )


async def _run(context: WorkflowContext, config: dict[str, Any] | None = None) -> list[Any]:
    run = MagicMock()
    run.id = "r1"
    return await execute(
        config=config or {},
        context=context,
        run=run,
        artifact_service=MagicMock(),
        node_id="n1",
        device_sessions=MagicMock(),
    )


class SplitStackDeviceTests(unittest.TestCase):
    def test_one_device_per_member_with_nautobot_identity(self) -> None:
        members = split_stack_device(_stack_device(), parse_split_settings({}))
        self.assertEqual([m.id for m in members], [_MASTER_ID, _MEMBER2_ID])
        self.assertEqual([m.name for m in members], ["LAB.local.zz", "LAB:2.local.zz"])
        for member in members:
            # update-nautobot-device only trusts a UUID id when source == "nautobot"
            self.assertEqual(member.source, "nautobot")
            self.assertEqual(member.source_id, "src")
            self.assertEqual(member.primary_ip4, "10.0.0.1/24")
            self.assertEqual(member.hostname, "10.0.0.1")
            self.assertEqual(member.status, DeviceStatus.OK)

    def test_member_bag_matches_split_mode_shape(self) -> None:
        stack = _stack_device()
        split_mode = build_stack_devices(
            _vc(), parse_settings({"split_members": True}), source_id="src", node_id="n0"
        )
        members = split_stack_device(stack, parse_split_settings({}))
        self.assertEqual(
            [m.attribute_bags["virtual_chassis"] for m in members],
            [d.attribute_bags["virtual_chassis"] for d in split_mode],
        )

    def test_parsed_output_is_kept_on_every_member(self) -> None:
        members = split_stack_device(_stack_device(), parse_split_settings({}))
        for member in members:
            self.assertIn("show version", member.parsed["parsed"])
            self.assertIn(Capability.PARSED, member.capabilities)

    def test_update_attribute_recipe_reads_each_members_own_serial_and_model(self) -> None:
        members = split_stack_device(_stack_device(), parse_split_settings({}))
        base = "parsed.parsed.show version.parsed[0]"
        serials = [
            resolve_device_attribute(m, f"{base}.serial[{{virtual_chassis.stack_index}}]")
            for m in members
        ]
        models = [
            resolve_device_attribute(m, f"{base}.hardware[{{virtual_chassis.stack_index}}]")
            for m in members
        ]
        self.assertEqual(serials, ["serial1", "serial2"])
        self.assertEqual(models, ["WS-C3850-48T", "WS-C3850-12S"])

    def test_position_selector_reads_switch_detail_per_member(self) -> None:
        members = split_stack_device(_stack_device(), parse_split_settings({}))
        path = "parsed.parsed.show switch detail.parsed[switch={virtual_chassis.position}].role"
        self.assertEqual(
            [resolve_device_attribute(m, path) for m in members], ["Active", "Standby"]
        )

    def test_device_without_stack_bag_is_not_splittable(self) -> None:
        plain = DeviceContext(id="d1", name="d1", hostname="d1")
        self.assertIsNone(split_stack_device(plain, parse_split_settings({})))

    def test_already_split_member_is_not_splittable(self) -> None:
        (member, *_) = build_stack_devices(
            _vc(), parse_settings({"split_members": True}), source_id="src", node_id="n0"
        )
        self.assertIsNone(split_stack_device(member, parse_split_settings({})))

    def test_input_device_is_not_mutated(self) -> None:
        stack = _stack_device()
        before = stack.model_dump()
        split_stack_device(stack, parse_split_settings({}))
        self.assertEqual(stack.model_dump(), before)

    def test_custom_attribute_bag(self) -> None:
        settings = parse_settings({"attribute_bag": "vc"})
        (stack,) = build_stack_devices(_vc(), settings, source_id="src", node_id="n0")
        members = split_stack_device(stack, parse_split_settings({"attribute_bag": "vc"}))
        assert members is not None
        self.assertEqual(members[1].attribute_bags["vc"]["position"], 2)


class SettingsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        self.assertEqual(parse_split_settings({}).attribute_bag, "virtual_chassis")

    def test_reserved_or_dotted_bag_name_rejected(self) -> None:
        for bad in ("parsed", "run_input", "a.b", "name"):
            with self.assertRaises(ValueError, msg=bad):
                parse_split_settings({"attribute_bag": bad})


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_replaces_stack_with_members(self) -> None:
        stack = _stack_device()
        outcomes = await _run(_context(stack))
        self.assertEqual([o.name for o in outcomes], ["success"])
        devices = outcomes[0].context.devices
        self.assertEqual(set(devices), {_MASTER_ID, _MEMBER2_ID})
        self.assertEqual(devices[_MEMBER2_ID].name, "LAB:2.local.zz")
        self.assertEqual(outcomes[0].context.metadata["keep"], 1)

    async def test_non_stack_device_goes_to_failure_and_stack_still_splits(self) -> None:
        plain = DeviceContext(id="plain", name="plain", hostname="plain")
        outcomes = await _run(_context(_stack_device(), plain))
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(set(by_name["success"].context.devices), {_MASTER_ID, _MEMBER2_ID})
        failed = by_name["failure"].context.devices["plain"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[0].code, "not_a_stack")
        self.assertEqual(failed.errors[0].step_id, "split-virtual-chassis")

    async def test_failed_stack_device_is_passed_to_failure_untouched(self) -> None:
        failed = _stack_device().model_copy(update={"status": DeviceStatus.FAILED})
        outcomes = await _run(_context(failed))
        by_name = {o.name: o for o in outcomes}
        self.assertEqual(by_name["success"].context.devices, {})
        self.assertEqual(len(by_name["failure"].context.devices), 1)
        self.assertEqual(by_name["failure"].context.devices[failed.id].errors, failed.errors)

    async def test_empty_context_is_a_trivial_success(self) -> None:
        outcomes = await _run(_context())
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertEqual(outcomes[0].context.devices, {})

    async def test_input_context_is_not_mutated(self) -> None:
        context = _context(_stack_device())
        before = context.model_dump()
        await _run(context)
        self.assertEqual(context.model_dump(), before)

    async def test_invalid_config_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            await _run(_context(_stack_device()), {"attribute_bag": "parsed"})

    async def test_member_id_collision_fails_the_colliding_devices(self) -> None:
        """Two stack devices claiming the same member UUID must not silently overwrite."""
        first = _stack_device()
        second = first.model_copy(update={"id": "other-stack"})
        outcomes = await _run(_context(first, second))
        by_name = {o.name: o for o in outcomes}
        self.assertIn("failure", by_name)
        self.assertEqual(len(by_name["success"].context.devices), 2)


if __name__ == "__main__":
    unittest.main()
