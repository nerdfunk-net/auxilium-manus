"""Tests for ``{placeholder}`` expansion inside attribute path brackets."""

from __future__ import annotations

import os
import unittest
from typing import Any
from unittest.mock import MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.workflow_context.attribute_path import (
    AttributeState,
    expand_path_placeholders,
    resolve_device_attribute,
    resolve_device_attribute_state,
    resolve_device_value,
)
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.update_attribute.executor import execute

_VERSION = "parsed.cmd.show version.parsed[0]"
_SWITCH = "parsed.cmd.show switch detail.parsed"

_PARSED: dict[str, Any] = {
    "cmd": {
        "show version": {
            "parsed": [
                {
                    "hostname": "LAB.local.zz",
                    "hardware": ["WS-C3850-48T", "WS-C3850-12S"],
                    "serial": ["serial1", "serial2"],
                    "mac_address": ["aaaa.bbbb.cccc", "a1a1.b1b1.c1c1"],
                }
            ],
            "error": None,
        },
        "show switch detail": {
            "parsed": [
                {"switch": "1", "role": "Active", "mac_address": "aaaa.bbbb.cccc"},
                {"switch": "2", "role": "Standby", "mac_address": "a1a1.b1b1.c1c1"},
            ],
            "error": None,
        },
    }
}


def _device(stack_index: int = 1, **bag: Any) -> DeviceContext:
    return DeviceContext(
        id="d1",
        name="LAB:2.local.zz",
        hostname="10.0.0.1",
        attribute_bags={
            "virtual_chassis": {"stack_index": stack_index, "position": stack_index + 1, **bag}
        },
        parsed=_PARSED,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


class ExpandPlaceholdersTests(unittest.TestCase):
    def test_path_without_braces_is_returned_unchanged(self) -> None:
        self.assertEqual(expand_path_placeholders(_device(), "a.b[0].c"), "a.b[0].c")

    def test_placeholder_inside_index_bracket(self) -> None:
        path = f"{_VERSION}.serial[{{virtual_chassis.stack_index}}]"
        self.assertEqual(expand_path_placeholders(_device(1), path), f"{_VERSION}.serial[1]")

    def test_placeholder_inside_filter_value(self) -> None:
        path = "x[switch={virtual_chassis.position}].role"
        self.assertEqual(expand_path_placeholders(_device(1), path), "x[switch=2].role")

    def test_unresolved_placeholder_gives_none(self) -> None:
        self.assertIsNone(expand_path_placeholders(_device(), "x[{virtual_chassis.nope}]"))

    def test_placeholder_outside_brackets_gives_none(self) -> None:
        self.assertIsNone(expand_path_placeholders(_device(), "x.{virtual_chassis.stack_index}"))

    def test_unclosed_or_nested_braces_give_none(self) -> None:
        self.assertIsNone(expand_path_placeholders(_device(), "x[{virtual_chassis.stack_index]"))
        self.assertIsNone(expand_path_placeholders(_device(), "x[{a{b}}]"))

    def test_value_with_bracket_characters_is_rejected(self) -> None:
        device = _device(note="a]b")
        self.assertIsNone(expand_path_placeholders(device, "x[note={virtual_chassis.note}]"))

    @patch.dict(os.environ, {"CREDENTIAL_ENCRYPTION_KEY": "test-secret-key-placeholders"})
    def test_sealed_secret_is_never_embedded(self) -> None:
        device = _device(token=seal_secret("s3cr3t"))
        self.assertIsNone(expand_path_placeholders(device, "x[token={virtual_chassis.token}]"))

    def test_inner_placeholder_may_itself_contain_brackets(self) -> None:
        path = f"x[{{{_VERSION}.serial[0]}}]"
        self.assertEqual(expand_path_placeholders(_device(), path), "x[serial1]")


class ResolveWithPlaceholdersTests(unittest.TestCase):
    def test_serial_of_each_member_by_stack_index(self) -> None:
        path = f"{_VERSION}.serial[{{virtual_chassis.stack_index}}]"
        self.assertEqual(resolve_device_attribute(_device(0), path), "serial1")
        self.assertEqual(resolve_device_attribute(_device(1), path), "serial2")

    def test_role_by_position_matches_switch_number(self) -> None:
        path = f"{_SWITCH}[switch={{virtual_chassis.position}}].role"
        self.assertEqual(resolve_device_attribute(_device(0), path), "Active")
        self.assertEqual(resolve_device_attribute(_device(1), path), "Standby")

    def test_join_by_mac_address_taken_from_other_command(self) -> None:
        device = _device(1, mac="a1a1.b1b1.c1c1")
        path = f"{_SWITCH}[mac_address={{virtual_chassis.mac}}].role"
        self.assertEqual(resolve_device_attribute(device, path), "Standby")

    def test_state_resolves_and_reports_absent_when_unresolved(self) -> None:
        good = f"{_VERSION}.hardware[{{virtual_chassis.stack_index}}]"
        state, value = resolve_device_attribute_state(_device(1), good)
        self.assertEqual((state, value), (AttributeState.PRESENT, "WS-C3850-12S"))

        bad = f"{_VERSION}.hardware[{{virtual_chassis.missing}}]"
        self.assertEqual(
            resolve_device_attribute_state(_device(1), bad), (AttributeState.ABSENT, None)
        )

    def test_value_returns_the_selected_item(self) -> None:
        path = f"{_SWITCH}[switch={{virtual_chassis.position}}]"
        value = resolve_device_value(_device(0), path)
        self.assertEqual(value["role"], "Active")

    def test_non_numeric_index_does_not_resolve(self) -> None:
        device = _device(0, label="abc")
        path = f"{_VERSION}.serial[{{virtual_chassis.label}}]"
        self.assertIsNone(resolve_device_attribute(device, path))

    def test_out_of_range_index_does_not_resolve(self) -> None:
        path = f"{_VERSION}.serial[{{virtual_chassis.stack_index}}]"
        self.assertIsNone(resolve_device_attribute(_device(5), path))


@patch.dict(os.environ, {"CREDENTIAL_ENCRYPTION_KEY": "test-secret-key-placeholders"})
class UpdateAttributeWithPlaceholdersTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, attribute: dict[str, Any], device: DeviceContext) -> DeviceContext:
        context = WorkflowContext(run_id="r", workflow_id="w", devices={"d1": device})
        outcomes = await execute(
            config={"attributes": [attribute]},
            context=context,
            run=MagicMock(),
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )
        return outcomes[0].context.devices["d1"]

    async def test_regex_mode_source_path_with_placeholder(self) -> None:
        updated = await self._run(
            {
                "mode": "regex",
                "source_path": f"{_VERSION}.mac_address[{{virtual_chassis.stack_index}}]",
                "pattern": "(.+)",
                "destination_template": r"\1",
                "destination_path": "virtual_chassis.mac",
            },
            _device(1),
        )
        self.assertEqual(resolve_device_attribute(updated, "virtual_chassis.mac"), "a1a1.b1b1.c1c1")

    async def test_template_mode_nested_placeholder(self) -> None:
        updated = await self._run(
            {
                "mode": "template",
                "template": f"{{{_VERSION}.serial[{{virtual_chassis.stack_index}}]}}",
                "destination_path": "virtual_chassis.serial",
            },
            _device(1),
        )
        self.assertEqual(resolve_device_attribute(updated, "virtual_chassis.serial"), "serial2")

    async def test_template_mode_two_step_join_by_mac(self) -> None:
        first = await self._run(
            {
                "mode": "template",
                "template": f"{{{_VERSION}.mac_address[{{virtual_chassis.stack_index}}]}}",
                "destination_path": "virtual_chassis.mac",
            },
            _device(1),
        )
        second = await self._run(
            {
                "mode": "template",
                "template": f"{{{_SWITCH}[mac_address={{virtual_chassis.mac}}].role}}",
                "destination_path": "virtual_chassis.role",
            },
            first,
        )
        self.assertEqual(resolve_device_attribute(second, "virtual_chassis.role"), "Standby")

    async def test_template_with_braces_around_plain_placeholder_is_unchanged(self) -> None:
        updated = await self._run(
            {
                "mode": "template",
                "template": '{"name": "{virtual_chassis.stack_index}"}',
                "destination_path": "virtual_chassis.json",
            },
            _device(1),
        )
        self.assertEqual(resolve_device_attribute(updated, "virtual_chassis.json"), '{"name": "1"}')

    async def test_unresolved_nested_placeholder_skips_the_write(self) -> None:
        updated = await self._run(
            {
                "mode": "template",
                "template": f"{{{_VERSION}.serial[{{virtual_chassis.missing}}]}}",
                "destination_path": "virtual_chassis.serial",
            },
            _device(1),
        )
        self.assertIsNone(resolve_device_attribute(updated, "virtual_chassis.serial"))


class ValueShapeTests(unittest.TestCase):
    def test_equals_sign_in_value_is_rejected(self) -> None:
        device = _device(note="switch=1")
        self.assertIsNone(expand_path_placeholders(device, "serial[{virtual_chassis.note}]"))
        self.assertIsNone(expand_path_placeholders(device, "items[{virtual_chassis.note}=literal]"))

    def test_equals_sign_cannot_turn_an_index_into_a_filter(self) -> None:
        device = _device(note="switch=1")
        path = f"{_SWITCH}[{{virtual_chassis.note}}].role"
        self.assertIsNone(resolve_device_attribute(device, path))


@patch.dict(os.environ, {"CREDENTIAL_ENCRYPTION_KEY": "test-secret-key-placeholders"})
class TemplateNestingTests(unittest.IsolatedAsyncioTestCase):
    async def _render(self, template: str, device: DeviceContext) -> DeviceContext:
        context = WorkflowContext(run_id="r", workflow_id="w", devices={"d1": device})
        outcomes = await execute(
            config={
                "attributes": [
                    {"mode": "template", "template": template, "destination_path": "out.value"}
                ]
            },
            context=context,
            run=MagicMock(),
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )
        return outcomes[0].context.devices["d1"]

    async def test_inner_path_with_its_own_brackets(self) -> None:
        device = _device(1, mac="x")
        template = (
            f"{{{_SWITCH}[mac_address={{{_VERSION}.mac_address[{{virtual_chassis.stack_index}}]}}]"
            ".role}"
        )
        updated = await self._render(template, device)
        self.assertEqual(resolve_device_attribute(updated, "out.value"), "Standby")

    async def test_unresolved_inner_path_with_brackets_skips_the_write(self) -> None:
        template = (
            f"{{{_SWITCH}[mac_address={{{_VERSION}.mac_address[{{virtual_chassis.nope}}]}}].role}}"
        )
        updated = await self._render(template, _device(1))
        self.assertIsNone(resolve_device_attribute(updated, "out.value"))

    async def test_surrounding_text_and_two_placeholders(self) -> None:
        template = "{virtual_chassis.stack_index}/{virtual_chassis.position}: [ok]"
        updated = await self._render(template, _device(1))
        self.assertEqual(resolve_device_attribute(updated, "out.value"), "1/2: [ok]")


if __name__ == "__main__":
    unittest.main()
