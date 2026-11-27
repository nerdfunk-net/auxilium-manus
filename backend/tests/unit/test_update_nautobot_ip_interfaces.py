"""Tests for the "IP addresses from interfaces" mode of update-nautobot-ip."""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER
from tests.unit._step_helpers import make_context
from workflow_steps.update_nautobot_ip import address_values
from workflow_steps.update_nautobot_ip import executor as mod
from workflow_steps.update_nautobot_ip.address_values import AddressRef, render_address_value
from workflow_steps.update_nautobot_ip.executor import _parse_config, execute

_STATUS_ID = "44444444-4444-4444-4444-444444444444"
_NS_ID = "11111111-1111-1111-1111-111111111111"
_IF1 = "10000000-0000-0000-0000-000000000001"
_IF2 = "10000000-0000-0000-0000-000000000002"
_IP1 = "a1000000-0000-0000-0000-000000000001"
_IP2 = "a2000000-0000-0000-0000-000000000002"
_IP6 = "a6000000-0000-0000-0000-000000000006"


def _ip(ip_id: str, address: str, version: int = 4) -> dict[str, Any]:
    return {"id": ip_id, "address": address, "ip_version": version}


def _iface(iface_id: str, name: str, *addresses: dict[str, Any]) -> dict[str, Any]:
    return {"id": iface_id, "name": name, "ip_addresses": list(addresses)}


def _device(did: str = "d1", interfaces: list | None = None, **bags: Any) -> DeviceContext:
    nautobot: dict[str, Any] = {} if interfaces is None else {"interfaces": interfaces}
    return DeviceContext(
        id=did,
        name=did,
        hostname=did,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
        attribute_bags={"nautobot": nautobot, **bags},
    )


def _config(**overrides: Any) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "nautobot_source_id": "src",
        "ips_from_interfaces": True,
        "status": "Active",
    }
    cfg.update(overrides)
    return cfg


async def _run(config: dict, context: WorkflowContext, common: Any = None):
    common = common or MagicMock()
    defaults = (
        ("resolve_status_id", _STATUS_ID),
        ("resolve_namespace_id", _NS_ID),
        ("resolve_role_id_for_content_type", "role-id"),
        ("update_ip_address", True),
        ("plan_ip_update", {"status": _STATUS_ID}),
        ("shared_ip_ids", set()),
    )
    for name, value in defaults:
        if not isinstance(getattr(common, name, None), AsyncMock):
            setattr(common, name, AsyncMock(return_value=value))
    bound = mod._Bound(common=common, client=MagicMock())
    with patch.object(mod, "_bind_nautobot", return_value=bound):
        outcomes = await execute(
            config=config,
            context=context,
            run=MagicMock(id="r"),
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )
    return {o.name: o.context for o in outcomes}, common


def _counts(out: dict) -> dict:
    return out["success"].metadata["n1.update_ip_counts"]


class ParseConfigTests(unittest.TestCase):
    def test_mode_needs_no_ip_id_but_one_field(self) -> None:
        parsed = _parse_config(_config())
        self.assertTrue(parsed.from_interfaces)
        with self.assertRaises(ValueError):
            _parse_config(_config(status=""))

    def test_mode_refuses_an_ip_id(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(ip_id=_IP1))

    def test_ip_id_is_still_required_without_the_mode(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config({"nautobot_source_id": "s", "status": "Active"})

    def test_dry_run_is_refused_in_the_manual_mode_instead_of_writing(self) -> None:
        manual = {"nautobot_source_id": "s", "ip_id": _IP1, "status": "Active"}
        for flag in (True, "true"):
            with self.assertRaises(ValueError, msg=repr(flag)):
                _parse_config({**manual, "dry_run": flag})
        self.assertFalse(_parse_config({**manual, "dry_run": False}).dry_run)

    def test_ip_version_and_dry_run(self) -> None:
        parsed = _parse_config(_config(ip_version="6", dry_run="true"))
        self.assertEqual((parsed.ip_version, parsed.dry_run), ("6", True))
        self.assertEqual(_parse_config(_config(ip_version=4)).ip_version, "4")
        with self.assertRaises(ValueError):
            _parse_config(_config(ip_version="5"))


class AddressValueTests(unittest.TestCase):
    _ref = AddressRef(id=_IP1, address="10.1.2.3/24", interface_name="Gi0/0.100", interface_id=_IF1)

    def test_tokens(self) -> None:
        device = _device(custom={"site": "lab"})
        render = lambda raw: render_address_value(raw, device, self._ref, field="dns_name")  # noqa: E731
        self.assertEqual(render("{ip.address}"), "10.1.2.3/24")
        self.assertEqual(render("{ip.host}"), "10.1.2.3")
        self.assertEqual(render("{interface.name}"), "Gi0/0.100")
        self.assertEqual(
            render("{interface.slug}.{custom.site}.example.org"), "gi0-0-100.lab.example.org"
        )

    def test_fixed_text_is_unchanged(self) -> None:
        self.assertEqual(
            render_address_value("uplink", _device(), self._ref, field="description"), "uplink"
        )

    def test_unresolved_placeholder_is_an_error_not_empty_text(self) -> None:
        result = render_address_value("{custom.nope}.x", _device(), self._ref, field="dns_name")
        self.assertIsInstance(result, tuple)
        self.assertEqual(result[0], "dns_name_unresolved")

    def test_secret_placeholder_is_refused(self) -> None:
        with patch.object(
            address_values, "resolve_device_attribute", return_value=REDACTED_PLACEHOLDER
        ):
            result = render_address_value(
                "x-{custom.pw}", _device(), self._ref, field="description"
            )
        self.assertEqual(result[0], "description_is_secret")

    def test_a_token_value_cannot_inject_a_placeholder(self) -> None:
        ref = AddressRef(
            id=_IP1, address="10.0.0.1/24", interface_name="{custom.site}", interface_id=_IF1
        )
        device = _device(custom={"site": "lab"})
        self.assertNotIn(
            "lab", render_address_value("{interface.name}", device, ref, field="description")
        )


class InterfaceModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_updates_each_distinct_address_once(self) -> None:
        interfaces = [
            _iface(_IF1, "Gi0/0", _ip(_IP1, "10.0.0.1/24")),
            _iface(_IF2, "Gi0/1", _ip(_IP1, "10.0.0.1/24"), _ip(_IP2, "10.0.1.1/24")),
        ]
        out, common = await _run(
            _config(), make_context([_device("a", interfaces)], run_id="r", workflow_id="w")
        )
        calls = common.update_ip_address.await_args_list
        self.assertEqual({c.args[0] for c in calls}, {_IP1, _IP2})
        self.assertEqual(len(calls), 2)
        for call in calls:
            self.assertEqual(call.args[1], {"status": _STATUS_ID})
            self.assertIsNone(call.kwargs.get("find_parent"))
        self.assertIn("a", out["success"].devices)
        self.assertEqual(_counts(out)["updated"], 2)

    async def test_ip_version_filter(self) -> None:
        interfaces = [
            _iface(_IF1, "Gi0/0", _ip(_IP1, "10.0.0.1/24"), _ip(_IP6, "2001:db8::1/64", 6))
        ]
        _, common = await _run(
            _config(ip_version="6"),
            make_context([_device("a", interfaces)], run_id="r", workflow_id="w"),
        )
        self.assertEqual([c.args[0] for c in common.update_ip_address.await_args_list], [_IP6])

    async def test_shared_addresses_are_skipped_and_counted(self) -> None:
        interfaces = [_iface(_IF1, "Gi0/0", _ip(_IP1, "10.0.0.1/24"), _ip(_IP2, "10.0.0.2/24"))]
        common = MagicMock()
        common.shared_ip_ids = AsyncMock(return_value={_IP2})
        out, common = await _run(
            _config(), make_context([_device("a", interfaces)], run_id="r", workflow_id="w"), common
        )
        self.assertEqual([c.args[0] for c in common.update_ip_address.await_args_list], [_IP1])
        common.shared_ip_ids.assert_awaited_once()
        self.assertEqual(common.shared_ip_ids.await_args.args[1], {_IF1})
        self.assertEqual(_counts(out)["skipped_shared"], 1)

    async def test_per_address_values(self) -> None:
        interfaces = [_iface(_IF1, "Gi0/0", _ip(_IP1, "10.0.0.1/24"))]
        out, common = await _run(
            _config(
                dns_name="{interface.slug}.{custom.site}.example.org",
                description="{interface.name} {ip.address}",
            ),
            make_context(
                [_device("a", interfaces, custom={"site": "lab"})], run_id="r", workflow_id="w"
            ),
        )
        fields = common.update_ip_address.await_args.args[1]
        self.assertEqual(fields["dns_name"], "gi0-0.lab.example.org")
        self.assertEqual(fields["description"], "Gi0/0 10.0.0.1/24")
        self.assertIn("a", out["success"].devices)

    async def test_unresolved_value_fails_the_device_before_any_write(self) -> None:
        interfaces = [_iface(_IF1, "Gi0/0", _ip(_IP1, "10.0.0.1/24"))]
        out, common = await _run(
            _config(dns_name="{custom.nope}.x"),
            make_context([_device("a", interfaces)], run_id="r", workflow_id="w"),
        )
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "dns_name_unresolved")
        common.update_ip_address.assert_not_awaited()

    async def test_an_address_whose_value_renders_empty_is_skipped_not_fatal(self) -> None:
        # "///" has no letter or digit, so {interface.slug} is empty for that one address only.
        interfaces = [
            _iface(_IF1, "///", _ip(_IP1, "10.0.0.1/24")),
            _iface(_IF2, "Gi0/1", _ip(_IP2, "10.0.1.1/24")),
        ]
        out, common = await _run(
            _config(status="", description="{interface.slug}"),
            make_context([_device("a", interfaces)], run_id="r", workflow_id="w"),
        )
        self.assertEqual([c.args[0] for c in common.update_ip_address.await_args_list], [_IP2])
        self.assertIn("a", out["success"].devices)
        self.assertNotIn("a", out["failure"].devices)
        counts = _counts(out)
        self.assertEqual((counts["updated"], counts["skipped_empty"]), (1, 1))

    async def test_the_dry_run_names_the_addresses_skipped_for_an_empty_value(self) -> None:
        interfaces = [_iface(_IF1, "///", _ip(_IP1, "10.0.0.1/24"))]
        out, common = await _run(
            _config(status="", description="{interface.slug}", dry_run=True),
            make_context([_device("a", interfaces)], run_id="r", workflow_id="w"),
        )
        common.update_ip_address.assert_not_awaited()
        common.plan_ip_update.assert_not_awaited()
        preview = out["success"].devices["a"].dry_run_results["n1"]
        self.assertEqual(preview["skipped_empty"], [{"ip_id": _IP1, "address": "10.0.0.1/24"}])
        self.assertEqual(preview["would_change"], [])

    async def test_an_empty_value_never_uses_the_empty_configuration_code(self) -> None:
        interfaces = [_iface(_IF1, ".", _ip(_IP1, "10.0.0.1/24"))]
        out, _ = await _run(
            _config(status="", description="{interface.slug}"),
            make_context([_device("a", interfaces)], run_id="r", workflow_id="w"),
        )
        self.assertNotIn("a", out["failure"].devices)

    async def test_a_value_that_is_empty_for_every_device_level_field_still_fails(self) -> None:
        # status resolves to nothing at device level: a configuration problem, not a skipped one.
        interfaces = [_iface(_IF1, "Gi0/0", _ip(_IP1, "10.0.0.1/24"))]
        out, common = await _run(
            _config(status="{custom.nope}"),
            make_context([_device("a", interfaces)], run_id="r", workflow_id="w"),
        )
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "status_unresolved")
        common.update_ip_address.assert_not_awaited()

    async def test_namespace_makes_a_parent_finder(self) -> None:
        interfaces = [_iface(_IF1, "Gi0/0", _ip(_IP1, "10.0.0.1/24"))]
        _, common = await _run(
            _config(status="", namespace="Global"),
            make_context([_device("a", interfaces)], run_id="r", workflow_id="w"),
        )
        self.assertIsNotNone(common.update_ip_address.await_args.kwargs["find_parent"])

    async def test_dry_run_writes_nothing_and_previews_field_names(self) -> None:
        interfaces = [_iface(_IF1, "Gi0/0", _ip(_IP1, "10.0.0.1/24"), _ip(_IP2, "10.0.0.2/24"))]
        common = MagicMock()
        common.plan_ip_update = AsyncMock(
            side_effect=lambda ip_id, *_a, **_k: {"status": "x"} if ip_id == _IP1 else {}
        )
        out, common = await _run(
            _config(dry_run=True),
            make_context([_device("a", interfaces)], run_id="r", workflow_id="w"),
            common,
        )
        common.update_ip_address.assert_not_awaited()
        preview = out["success"].devices["a"].dry_run_results["n1"]
        self.assertEqual(
            preview["would_change"],
            [{"ip_id": _IP1, "address": "10.0.0.1/24", "fields": ["status"]}],
        )
        self.assertEqual(preview["unchanged"], 1)
        self.assertEqual(preview["skipped_shared"], [])
        counts = _counts(out)
        self.assertEqual((counts["updated"], counts["unchanged"], counts["dry_run"]), (1, 1, True))

    async def test_dry_run_names_a_namespace_move_as_namespace(self) -> None:
        interfaces = [_iface(_IF1, "Gi0/0", _ip(_IP1, "10.0.0.1/24"))]
        common = MagicMock()
        common.plan_ip_update = AsyncMock(return_value={"parent": "p"})
        out, _ = await _run(
            _config(status="", namespace="Global", dry_run=True),
            make_context([_device("a", interfaces)], run_id="r", workflow_id="w"),
            common,
        )
        preview = out["success"].devices["a"].dry_run_results["n1"]
        self.assertEqual(preview["would_change"][0]["fields"], ["namespace"])

    async def test_one_failing_address_fails_the_device_but_not_the_others(self) -> None:
        interfaces = [_iface(_IF1, "Gi0/0", _ip(_IP1, "10.0.0.1/24"), _ip(_IP2, "10.0.0.2/24"))]

        async def update(ip_id, *_a, **_k):
            if ip_id == _IP2:
                raise RuntimeError("boom")
            return True

        common = MagicMock()
        common.update_ip_address = AsyncMock(side_effect=update)
        out, common = await _run(
            _config(), make_context([_device("a", interfaces)], run_id="r", workflow_id="w"), common
        )
        self.assertEqual(common.update_ip_address.await_count, 2)
        error = out["failure"].devices["a"].errors[0]
        self.assertIn("1 of 2 addresses", error.message)
        self.assertEqual(out["failure"].metadata["n1.update_ip_counts"]["failed"], 1)

    async def test_missing_interfaces_fail_the_device(self) -> None:
        out, common = await _run(
            _config(), make_context([_device("a", None)], run_id="r", workflow_id="w")
        )
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "interfaces_missing")
        common.update_ip_address.assert_not_awaited()

    async def test_device_without_addresses_succeeds_without_lookups(self) -> None:
        out, common = await _run(
            _config(),
            make_context([_device("a", [_iface(_IF1, "lo0")])], run_id="r", workflow_id="w"),
        )
        self.assertIn("a", out["success"].devices)
        common.shared_ip_ids.assert_not_awaited()

    async def test_unknown_status_fails_the_device(self) -> None:
        interfaces = [_iface(_IF1, "Gi0/0", _ip(_IP1, "10.0.0.1/24"))]
        common = MagicMock()
        common.resolve_status_id = AsyncMock(side_effect=ValueError("nope"))
        out, _ = await _run(
            _config(status="Nowhere"),
            make_context([_device("a", interfaces)], run_id="r", workflow_id="w"),
            common,
        )
        error = out["failure"].devices["a"].errors[0]
        self.assertEqual(error.code, "status_not_found")
        self.assertNotIn("Nowhere", error.message)

    async def test_status_lookup_is_made_once_for_all_devices(self) -> None:
        one = [_iface(_IF1, "Gi0/0", _ip(_IP1, "10.0.0.1/24"))]
        two = [_iface(_IF2, "Gi0/0", _ip(_IP2, "10.0.0.2/24"))]
        _, common = await _run(
            _config(),
            make_context([_device("a", one), _device("b", two)], run_id="r", workflow_id="w"),
        )
        self.assertEqual(common.resolve_status_id.await_count, 1)

    async def test_no_devices(self) -> None:
        out, _ = await _run(_config(), make_context([], run_id="r", workflow_id="w"))
        self.assertEqual(out["success"].devices, {})


if __name__ == "__main__":
    unittest.main()
