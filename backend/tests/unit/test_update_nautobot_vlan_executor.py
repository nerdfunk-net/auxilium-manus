"""Tests for workflow_steps/update_nautobot_vlan/executor.py."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from services.nautobot.common.exceptions import NautobotAmbiguousMatchError, NautobotNotFoundError
from services.nautobot.managers.location_assignments import PartialUpdateError
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER
from workflow_steps.common import nautobot_plan_fields as plan_fields
from workflow_steps.update_nautobot_vlan import executor as mod
from workflow_steps.update_nautobot_vlan.executor import _parse_config, execute, split_locations

_VLAN_ID = "55555555-5555-5555-5555-555555555555"
_STATUS_ID = "44444444-4444-4444-4444-444444444444"
_ROLE_ID = "33333333-3333-3333-3333-333333333333"
_GROUP_ID = "22222222-2222-2222-2222-222222222222"
_LOC_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_LOC_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def _device(did: str = "d1", **overrides: Any) -> DeviceContext:
    return DeviceContext(
        id=did,
        name=did,
        hostname=did,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
        **overrides,
    )


def _context(*devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(run_id="r", workflow_id="w", devices={d.id: d for d in devices})


def _config(**overrides) -> dict:
    cfg = {"nautobot_source_id": "src-1", "vlan_id": _VLAN_ID, "status": "Active"}
    cfg.update(overrides)
    return cfg


_LOCATIONS = {"Berlin": _LOC_A, "Munich": _LOC_B}


async def _run(config: dict, context: WorkflowContext, *, common=None):
    common = common or MagicMock()
    defaults = (
        ("resolve_status_id", _STATUS_ID),
        ("resolve_role_id_for_content_type", _ROLE_ID),
        ("resolve_vlan_group_id", _GROUP_ID),
        ("find_vlans", [_VLAN_ID]),
        ("update_vlan", True),
    )
    for name, value in defaults:
        if not isinstance(getattr(common, name, None), AsyncMock):
            setattr(common, name, AsyncMock(return_value=value))
    if not isinstance(getattr(common, "resolve_location_id_strict", None), AsyncMock):
        common.resolve_location_id_strict = AsyncMock(side_effect=_LOCATIONS.__getitem__)
    with patch.object(mod, "_bind_nautobot", return_value=mod._Bound(common=common)):
        outcomes = await execute(
            config=config,
            context=context,
            run=MagicMock(id="r"),
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )
    return {o.name: o.context for o in outcomes}, common


class ParseConfigTests(unittest.TestCase):
    def test_missing_source(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(nautobot_source_id=""))

    def test_needs_vlan_id_or_vid(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(vlan_id=""))
        self.assertEqual(_parse_config(_config(vlan_id="", vid="100")).vid_expression, "100")

    def test_nothing_to_update_is_a_config_error(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(status=""))

    def test_locations_alone_are_enough_and_are_split(self) -> None:
        parsed = _parse_config(_config(status="", locations="Berlin, Munich\n{x.y}"))
        self.assertEqual(parsed.location_expressions, ("Berlin", "Munich", "{x.y}"))
        self.assertEqual(parsed.locations_mode, "replace")

    def test_locations_list_is_accepted(self) -> None:
        parsed = _parse_config(_config(status="", locations=["Berlin", "Munich"]))
        self.assertEqual(parsed.location_expressions, ("Berlin", "Munich"))

    def test_invalid_mode(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(locations_mode="merge"))


class SplitLocationsTests(unittest.TestCase):
    def test_commas_and_new_lines(self) -> None:
        self.assertEqual(
            split_locations("Berlin, Munich\nHamburg"), ["Berlin", "Munich", "Hamburg"]
        )

    def test_quoted_name_keeps_its_comma(self) -> None:
        self.assertEqual(
            split_locations('"Frankfurt, West", Berlin'), ["Frankfurt, West", "Berlin"]
        )

    def test_blank_entries_are_dropped(self) -> None:
        self.assertEqual(split_locations(" , ,\n"), [])


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_partial_update_is_reported_as_such(self) -> None:
        common = MagicMock()
        error = PartialUpdateError(["fields"])
        error.__cause__ = RuntimeError("x")
        common.update_vlan = AsyncMock(side_effect=error)
        out, _ = await _run(_config(), _context(_device("a")), common=common)
        failure = out["failure"].devices["a"].errors[0]
        self.assertEqual(failure.code, "vlan_partially_updated")
        self.assertIn("fields already written", failure.message)
        self.assertIn("run the step again", failure.message)

    async def test_quoted_location_with_comma_is_one_location(self) -> None:
        common = MagicMock()
        common.resolve_location_id_strict = AsyncMock(side_effect=lambda n: "id-" + n)
        out, common = await _run(
            _config(locations='"Frankfurt, West", Berlin'), _context(_device("a")), common=common
        )
        self.assertEqual(
            [c.args[0] for c in common.resolve_location_id_strict.call_args_list],
            ["Frankfurt, West", "Berlin"],
        )

    async def test_fields_and_locations_are_resolved_and_sent(self) -> None:
        cfg = _config(
            name="CLIENT",
            description="clients",
            role="Client access",
            locations="Berlin, Munich",
            locations_mode="add",
        )
        out, common = await _run(cfg, _context(_device("a")))
        self.assertIn("a", out["success"].devices)
        args, kwargs = common.update_vlan.call_args
        self.assertEqual(args[0], _VLAN_ID)
        self.assertEqual(
            args[1],
            {
                "name": "CLIENT",
                "description": "clients",
                "status": _STATUS_ID,
                "role": _ROLE_ID,
            },
        )
        self.assertEqual(kwargs, {"locations": (_LOC_A, _LOC_B), "locations_mode": "add"})
        common.resolve_status_id.assert_called_once_with("Active", content_type="ipam.vlan")
        common.resolve_role_id_for_content_type.assert_called_once_with(
            "Client access", "ipam.vlan"
        )

    async def test_vid_and_group_find_the_vlan(self) -> None:
        cfg = _config(vlan_id="", vid="100", vlan_group="Campus")
        out, common = await _run(cfg, _context(_device("a")))
        self.assertIn("a", out["success"].devices)
        common.find_vlans.assert_called_once_with(100, _GROUP_ID)
        self.assertEqual(common.update_vlan.call_args.args[0], _VLAN_ID)

    async def test_no_vlan_with_vid_fails_the_device(self) -> None:
        common = MagicMock()
        common.find_vlans = AsyncMock(return_value=[])
        out, common = await _run(
            _config(vlan_id="", vid="100"), _context(_device("a")), common=common
        )
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "vlan_not_found")
        common.update_vlan.assert_not_called()

    async def test_several_vlans_with_vid_are_ambiguous(self) -> None:
        common = MagicMock()
        common.find_vlans = AsyncMock(return_value=[_VLAN_ID, _LOC_A])
        out, common = await _run(
            _config(vlan_id="", vid="100"), _context(_device("a")), common=common
        )
        error = out["failure"].devices["a"].errors[0]
        self.assertEqual(error.code, "ambiguous_match")
        self.assertEqual(error.failure.kind, "ambiguous_match")
        common.update_vlan.assert_not_called()

    async def test_invalid_vlan_id_and_vid(self) -> None:
        out, _ = await _run(_config(vlan_id="not-a-uuid"), _context(_device("a")))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "vlan_id_invalid")
        for bad in ("0", "4095", "abc"):
            out, _ = await _run(_config(vlan_id="", vid=bad), _context(_device("a")))
            self.assertEqual(out["failure"].devices["a"].errors[0].code, "vid_invalid")

    async def test_unknown_location_fails_without_echoing_the_name(self) -> None:
        common = MagicMock()
        common.resolve_location_id_strict = AsyncMock(side_effect=ValueError("Location not found"))
        out, _ = await _run(_config(locations="Secret-Site"), _context(_device("a")), common=common)
        error = out["failure"].devices["a"].errors[0]
        self.assertEqual(error.code, "location_not_found")
        self.assertNotIn("Secret-Site", error.message)

    async def test_ambiguous_location_name(self) -> None:
        common = MagicMock()
        common.resolve_location_id_strict = AsyncMock(side_effect=NautobotAmbiguousMatchError("x"))
        out, _ = await _run(_config(locations="Berlin"), _context(_device("a")), common=common)
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "ambiguous_match")

    async def test_unknown_role_and_group(self) -> None:
        common = MagicMock()
        common.resolve_role_id_for_content_type = AsyncMock(return_value=None)
        out, _ = await _run(_config(role="x"), _context(_device("a")), common=common)
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "role_not_found")
        common = MagicMock()
        common.resolve_vlan_group_id = AsyncMock(side_effect=ValueError("VLAN group not found"))
        out, _ = await _run(
            _config(vlan_id="", vid="10", vlan_group="x"), _context(_device("a")), common=common
        )
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "vlan_group_not_found")

    async def test_secret_values_are_refused(self) -> None:
        real = plan_fields.resolve_update_field_expression

        def fake(*, field_key, **kwargs):
            if field_key == "description":
                return REDACTED_PLACEHOLDER
            return real(field_key=field_key, **kwargs)

        dev = _device("a", attribute_bags={"custom": {"d": "s"}})
        with patch.object(plan_fields, "resolve_update_field_expression", side_effect=fake):
            out, common = await _run(_config(description="{custom.d}"), _context(dev))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "description_is_secret")
        common.update_vlan.assert_not_called()

    async def test_values_from_attributes(self) -> None:
        dev = _device("a", attribute_bags={"custom": {"vlan": _VLAN_ID, "site": "Berlin"}})
        out, common = await _run(
            _config(vlan_id="{custom.vlan}", locations="{custom.site}"), _context(dev)
        )
        self.assertIn("a", out["success"].devices)
        args, kwargs = common.update_vlan.call_args
        self.assertEqual(args[0], _VLAN_ID)
        self.assertEqual(kwargs["locations"], (_LOC_A,))

    async def test_lookups_resolved_once_for_all_devices(self) -> None:
        out, common = await _run(
            _config(role="Client", locations="Berlin"),
            _context(_device("a"), _device("b"), _device("c")),
        )
        self.assertEqual(len(out["success"].devices), 3)
        self.assertEqual(common.resolve_status_id.call_count, 1)
        self.assertEqual(common.resolve_role_id_for_content_type.call_count, 1)
        self.assertEqual(common.resolve_location_id_strict.call_count, 1)

    async def test_unchanged_vlan_succeeds_and_is_counted(self) -> None:
        common = MagicMock()
        common.update_vlan = AsyncMock(return_value=False)
        out, _ = await _run(_config(), _context(_device("a")), common=common)
        self.assertIn("a", out["success"].devices)
        counts = out["success"].metadata["n1.update_vlan_counts"]
        self.assertEqual((counts["updated"], counts["unchanged"]), (0, 1))

    async def test_missing_vlan_in_nautobot_fails_the_device(self) -> None:
        common = MagicMock()
        common.update_vlan = AsyncMock(side_effect=NautobotNotFoundError("gone"))
        out, _ = await _run(_config(), _context(_device("a")), common=common)
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "vlan_not_found")

    async def test_nautobot_refusal_fails_only_that_device(self) -> None:
        common = MagicMock()
        common.update_vlan = AsyncMock(side_effect=[RuntimeError("boom"), True])
        # Different descriptions: two writes. (Devices with one fixed target and the same values
        # share a single write and its result, see test_nautobot_write_groups.py.)
        devices = [
            _device(name, attribute_bags={"custom": {"d": name}}) for name in ("a", "b")
        ]
        out, _ = await _run(_config(description="{custom.d}"), _context(*devices), common=common)
        self.assertEqual(common.update_vlan.call_count, 2)
        self.assertEqual((len(out["success"].devices), len(out["failure"].devices)), (1, 1))

    async def test_no_devices_returns_empty_outcomes(self) -> None:
        out, _ = await _run(_config(), _context())
        self.assertEqual((out["success"].devices, out["failure"].devices), ({}, {}))
