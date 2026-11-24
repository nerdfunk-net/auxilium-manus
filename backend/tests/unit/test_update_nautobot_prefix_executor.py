"""Tests for workflow_steps/update_nautobot_prefix (manual mode and prefixes from interfaces)."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.nautobot.common.exceptions import NautobotNotFoundError
from services.nautobot.managers.location_assignments import PartialUpdateError
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER
from workflow_steps.common import nautobot_plan_fields as plan_fields
from workflow_steps.update_nautobot_prefix import executor as mod
from workflow_steps.update_nautobot_prefix.executor import _parse_config, execute

_PFX = "55555555-5555-5555-5555-555555555555"
_PFX2 = "56565656-5656-5656-5656-565656565656"
_NS = "66666666-6666-6666-6666-666666666666"
_STATUS = "44444444-4444-4444-4444-444444444444"
_LOC_A = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
_LOC_B = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
_LOCATIONS = {"Berlin": _LOC_A, "Munich": _LOC_B}


def _device(did: str = "d1", bag: dict | None = None, **overrides: Any) -> DeviceContext:
    return DeviceContext(
        id=did,
        name=did,
        hostname=did,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
        attribute_bags={"nautobot": bag} if bag is not None else {},
        **overrides,
    )


def _context(*devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(run_id="r", workflow_id="w", devices={d.id: d for d in devices})


def _config(**overrides: Any) -> dict:
    cfg = {"nautobot_source_id": "src", "prefix_id": _PFX, "status": "Active"}
    cfg.update(overrides)
    return cfg


async def _run(config: dict, context: WorkflowContext, common: Any = None):
    common = common or MagicMock()
    defaults = (
        ("resolve_status_id", _STATUS),
        ("resolve_role_id_for_content_type", "role-id"),
        ("resolve_namespace_id", _NS),
        ("find_prefixes", [_PFX]),
        ("update_prefix", True),
        ("missing_prefix_locations", [_LOC_A]),
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

    def test_needs_prefix_id_or_prefix(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(prefix_id=""))
        self.assertEqual(
            _parse_config(_config(prefix_id="", prefix="10.0.0.0/24")).prefix_expression,
            "10.0.0.0/24",
        )

    def test_nothing_to_update(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(status=""))

    def test_locations_alone_are_enough(self) -> None:
        parsed = _parse_config(_config(status="", locations="Berlin, Munich"))
        self.assertEqual(parsed.location_expressions, ("Berlin", "Munich"))

    def test_dry_run_is_refused_in_the_manual_mode_instead_of_writing(self) -> None:
        for flag in (True, "true"):
            with self.assertRaises(ValueError, msg=repr(flag)):
                _parse_config(_config(dry_run=flag))
        self.assertFalse(_parse_config(_config(dry_run=False)).dry_run)

    def test_invalid_mode(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(locations_mode="merge"))

    def test_interface_mode_needs_no_selector_and_refuses_other_fields(self) -> None:
        parsed = _parse_config({"nautobot_source_id": "s", "prefixes_from_interfaces": True})
        self.assertTrue(parsed.from_interfaces)
        for key in (
            "prefix_id",
            "prefix",
            "namespace",
            "description",
            "status",
            "role",
            "locations",
        ):
            with self.assertRaises(ValueError, msg=key):
                _parse_config(
                    {"nautobot_source_id": "s", "prefixes_from_interfaces": True, key: "x"}
                )


class ManualModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_updates_by_id(self) -> None:
        out, common = await _run(
            _config(locations="Berlin", locations_mode="add"), _context(_device("a"))
        )
        common.update_prefix.assert_awaited_once_with(
            _PFX, {"status": _STATUS}, locations=(_LOC_A,), locations_mode="add"
        )
        self.assertIn("a", out["success"].devices)
        self.assertEqual(out["success"].metadata["n1.update_prefix_counts"]["updated"], 1)

    async def test_prefix_and_namespace_find_the_prefix(self) -> None:
        out, common = await _run(
            _config(prefix_id="", prefix="10.0.0.0/24", namespace="Global"), _context(_device("a"))
        )
        common.find_prefixes.assert_awaited_once_with("10.0.0.0/24", _NS)
        self.assertIn("a", out["success"].devices)

    async def test_the_network_is_looked_up_in_its_canonical_form(self) -> None:
        _, common = await _run(
            _config(prefix_id="", prefix="2001:DB8::/32", namespace="Global"),
            _context(_device("a")),
        )
        common.find_prefixes.assert_awaited_once_with("2001:db8::/32", _NS)

    async def test_no_match_and_several_matches(self) -> None:
        cfg = _config(prefix_id="", prefix="10.0.0.0/24")
        common = MagicMock()
        common.find_prefixes = AsyncMock(return_value=[])
        out, _ = await _run(cfg, _context(_device("a")), common)
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "prefix_not_found")
        common = MagicMock()
        common.find_prefixes = AsyncMock(return_value=[_PFX, _PFX2])
        out, common = await _run(cfg, _context(_device("a")), common)
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "ambiguous_match")
        common.update_prefix.assert_not_awaited()

    async def test_invalid_values(self) -> None:
        out, _ = await _run(_config(prefix_id="nope"), _context(_device("a")))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "prefix_id_invalid")
        out, _ = await _run(_config(prefix_id="", prefix="10.0.0.5/24"), _context(_device("a")))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "prefix_invalid")

    async def test_namespace_is_ignored_when_the_prefix_id_is_set(self) -> None:
        # A UUID selects the prefix by itself: its namespace is neither looked up nor needed.
        out, common = await _run(_config(namespace="NoSuchNamespace"), _context(_device("a")))
        self.assertIn("a", out["success"].devices)
        common.resolve_namespace_id.assert_not_awaited()
        common.find_prefixes.assert_not_awaited()

    async def test_prefix_id_is_written_in_lower_case(self) -> None:
        mixed = "ABCDEF12-3456-7890-ABCD-EF1234567890"
        out, common = await _run(_config(prefix_id=mixed), _context(_device("a")))
        self.assertIn("a", out["success"].devices)
        self.assertEqual(common.update_prefix.await_args.args[0], mixed.lower())

    async def test_unchanged_is_counted(self) -> None:
        common = MagicMock()
        common.update_prefix = AsyncMock(return_value=False)
        out, _ = await _run(_config(), _context(_device("a")), common)
        self.assertEqual(out["success"].metadata["n1.update_prefix_counts"]["unchanged"], 1)

    async def test_partial_update_is_reported(self) -> None:
        common = MagicMock()
        error = PartialUpdateError(["fields"])
        error.__cause__ = RuntimeError("x")
        common.update_prefix = AsyncMock(side_effect=error)
        out, _ = await _run(_config(), _context(_device("a")), common)
        failure = out["failure"].devices["a"].errors[0]
        self.assertEqual(failure.code, "prefix_partially_updated")
        self.assertIn("run the step again", failure.message)

    async def test_missing_prefix_in_nautobot(self) -> None:
        common = MagicMock()
        common.update_prefix = AsyncMock(side_effect=NautobotNotFoundError("gone"))
        out, _ = await _run(_config(), _context(_device("a")), common)
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "prefix_not_found")

    async def test_unknown_location_does_not_echo_the_name(self) -> None:
        common = MagicMock()
        common.resolve_location_id_strict = AsyncMock(side_effect=ValueError("secret-name"))
        out, _ = await _run(_config(locations="Nowhere"), _context(_device("a")), common)
        error = out["failure"].devices["a"].errors[0]
        self.assertEqual(error.code, "location_not_found")
        self.assertNotIn("Nowhere", error.message)

    async def test_lookups_are_made_once_for_all_devices(self) -> None:
        _, common = await _run(_config(), _context(_device("a"), _device("b")))
        self.assertEqual(common.resolve_status_id.await_count, 1)

    async def test_secret_values_are_refused(self) -> None:
        real = plan_fields.resolve_update_field_expression

        def fake(**kwargs: Any) -> str | None:
            if kwargs["field_key"] == "status":
                return REDACTED_PLACEHOLDER
            return real(**kwargs)

        with patch.object(plan_fields, "resolve_update_field_expression", side_effect=fake):
            out, common = await _run(_config(status="{secrets.x}"), _context(_device("a")))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "status_is_secret")
        common.update_prefix.assert_not_awaited()

    async def test_no_devices(self) -> None:
        out, _ = await _run(_config(), _context())
        self.assertEqual(out["success"].devices, {})


def _prefix(prefix_id: str, net: str, locations: tuple[str, ...] = ()) -> dict:
    return {
        "id": prefix_id,
        "prefix": net,
        "locations": [{"id": loc} for loc in locations],
        "namespace": {"id": _NS, "name": "Global"},
    }


def _bag(location: str | None, interfaces: list | None) -> dict:
    bag: dict[str, Any] = {}
    if location:
        bag["location"] = {"id": location}
    if interfaces is not None:
        bag["interfaces"] = interfaces
    return bag


_IFACE_CFG = {"nautobot_source_id": "src", "prefixes_from_interfaces": True}


class InterfaceModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_adds_the_device_location_to_each_parent_prefix_once(self) -> None:
        interfaces = [
            {"ip_addresses": [{"parent": _prefix(_PFX, "10.0.0.0/24")}]},
            {
                "ip_addresses": [
                    {"parent": _prefix(_PFX, "10.0.0.0/24")},
                    {"parent": _prefix(_PFX2, "10.0.1.0/24")},
                ]
            },
            {"ip_addresses": []},
        ]
        out, common = await _run(_IFACE_CFG, _context(_device("a", _bag(_LOC_A, interfaces))))
        calls = common.update_prefix.await_args_list
        self.assertEqual({c.args[0] for c in calls}, {_PFX, _PFX2})
        for call in calls:
            self.assertEqual(call.args[1], {})
            self.assertEqual(call.kwargs, {"locations": [_LOC_A], "locations_mode": "add"})
        self.assertEqual(out["success"].metadata["n1.update_prefix_counts"]["updated"], 2)

    async def test_a_prefix_the_bag_shows_at_the_location_is_still_asked_of_nautobot(self) -> None:
        interfaces = [{"ip_addresses": [{"parent": _prefix(_PFX, "10.0.0.0/24", (_LOC_A,))}]}]
        common = MagicMock()
        common.update_prefix = AsyncMock(return_value=False)
        out, common = await _run(
            _IFACE_CFG, _context(_device("a", _bag(_LOC_A, interfaces))), common
        )
        common.update_prefix.assert_awaited_once()
        self.assertEqual(out["success"].metadata["n1.update_prefix_counts"]["unchanged"], 1)

    async def test_a_stale_bag_does_not_hide_a_missing_location_in_a_dry_run(self) -> None:
        interfaces = [{"ip_addresses": [{"parent": _prefix(_PFX, "10.0.0.0/24", (_LOC_A,))}]}]
        out, common = await _run(
            {**_IFACE_CFG, "dry_run": True}, _context(_device("a", _bag(_LOC_A, interfaces)))
        )
        common.missing_prefix_locations.assert_awaited_once_with(_PFX, [_LOC_A])
        preview = out["success"].devices["a"].dry_run_results["n1"]
        self.assertEqual(len(preview["would_add_location"]), 1)

    async def test_counts_are_per_pair_whatever_the_bag_says(self) -> None:
        for bag_locations in ((), (_LOC_A,)):
            interfaces = [
                {"ip_addresses": [{"parent": _prefix(_PFX, "10.0.0.0/24", bag_locations)}]}
            ]
            devices = [_device(f"d{i}", _bag(_LOC_A, interfaces)) for i in range(10)]
            common = MagicMock()
            common.update_prefix = AsyncMock(return_value=False)
            out, _ = await _run(_IFACE_CFG, _context(*devices), common)
            counts = out["success"].metadata["n1.update_prefix_counts"]
            self.assertEqual((counts["updated"], counts["unchanged"]), (0, 1), bag_locations)

    async def test_dry_run_previews_and_writes_nothing(self) -> None:
        interfaces = [{"ip_addresses": [{"parent": _prefix(_PFX, "10.0.0.0/24")}]}]
        out, common = await _run(
            {**_IFACE_CFG, "dry_run": True}, _context(_device("a", _bag(_LOC_A, interfaces)))
        )
        common.update_prefix.assert_not_awaited()
        common.missing_prefix_locations.assert_awaited_once_with(_PFX, [_LOC_A])
        preview = out["success"].devices["a"].dry_run_results["n1"]
        self.assertEqual(
            preview["would_add_location"],
            [{"prefix_id": _PFX, "prefix": "10.0.0.0/24", "namespace": "Global"}],
        )

    async def test_bag_without_parent_prefix_does_nothing(self) -> None:
        interfaces = [{"ip_addresses": [{"id": "x", "address": "10.0.0.1/24"}]}]
        out, common = await _run(_IFACE_CFG, _context(_device("a", _bag(_LOC_A, interfaces))))
        common.update_prefix.assert_not_awaited()
        self.assertIn("a", out["success"].devices)

    async def test_missing_location_or_interfaces_fail_the_device(self) -> None:
        out, _ = await _run(_IFACE_CFG, _context(_device("a", _bag(None, []))))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "device_location_missing")
        out, _ = await _run(_IFACE_CFG, _context(_device("a", _bag(_LOC_A, None))))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "interfaces_missing")


if __name__ == "__main__":
    unittest.main()
