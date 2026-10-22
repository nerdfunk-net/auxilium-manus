"""Tests for workflow_steps/update_nautobot_ip/executor.py."""

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
from services.nautobot.common.exceptions import NautobotAPIError, NautobotNotFoundError
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER
from workflow_steps.common.nautobot_prefix_lookup import not_found
from workflow_steps.update_nautobot_ip import executor as mod
from workflow_steps.update_nautobot_ip.executor import _parse_config, execute

_NS_ID = "11111111-1111-1111-1111-111111111111"
_STATUS_ID = "44444444-4444-4444-4444-444444444444"
_ROLE_ID = "33333333-3333-3333-3333-333333333333"
_PREFIX_ID = "22222222-2222-2222-2222-222222222222"
_IP_ID = "55555555-5555-5555-5555-555555555555"


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
    cfg = {"nautobot_source_id": "src-1", "ip_id": _IP_ID, "status": "Reserved"}
    cfg.update(overrides)
    return cfg


def _containing(*prefixes: tuple[str, str], seen: list[str] | None = None):
    async def rest_request(*, endpoint: str, method: str = "GET", data=None):
        assert "contains=" in endpoint, endpoint
        if seen is not None:
            seen.append(endpoint)
        return {"results": [{"id": pid, "prefix": text} for pid, text in prefixes]}

    return rest_request


async def _run(config: dict, context: WorkflowContext, *, common=None, rest=None):
    common = common or MagicMock()
    for name, value in (
        ("resolve_namespace_id", _NS_ID),
        ("resolve_status_id", _STATUS_ID),
        ("resolve_role_id_for_content_type", _ROLE_ID),
        ("update_ip_address", True),
    ):
        if not isinstance(getattr(common, name, None), AsyncMock):
            setattr(common, name, AsyncMock(return_value=value))
    client = MagicMock()
    client.rest_request = AsyncMock(side_effect=rest or _containing())
    bound = mod._Bound(common=common, client=client)
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


class ParseConfigTests(unittest.TestCase):
    def test_missing_source(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(nautobot_source_id=""))

    def test_missing_ip_id(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(ip_id=" "))

    def test_nothing_to_update_is_a_config_error(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(_config(status=""))

    def test_any_single_field_is_enough(self) -> None:
        for field in ("namespace", "type", "role", "status", "dns_name", "description"):
            base = {"nautobot_source_id": "s", "ip_id": _IP_ID, field: "x"}
            parsed = _parse_config(base)
            self.assertEqual(parsed.expressions[field], "x")


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_fields_are_resolved_and_sent(self) -> None:
        cfg = _config(
            namespace="Global",
            type="DHCP",
            role="Secondary",
            dns_name="host.example.org",
            description="moved",
        )
        out, common = await _run(cfg, _context(_device("a")))
        self.assertIn("a", out["success"].devices)
        args, kwargs = common.update_ip_address.call_args
        self.assertEqual(
            args,
            (
                _IP_ID,
                {
                    "type": "dhcp",
                    "role": _ROLE_ID,
                    "status": _STATUS_ID,
                    "dns_name": "host.example.org",
                    "description": "moved",
                },
            ),
        )
        # The namespace is never a field of the request: the move goes through find_parent.
        self.assertNotIn("namespace", args[1])
        self.assertTrue(callable(kwargs["find_parent"]))
        common.resolve_status_id.assert_called_once_with("Reserved", content_type="ipam.ipaddress")
        common.resolve_role_id_for_content_type.assert_called_once_with(
            "Secondary", "ipam.ipaddress"
        )

    async def test_only_configured_fields_are_sent(self) -> None:
        _, common = await _run(_config(), _context(_device("a")))
        args, kwargs = common.update_ip_address.call_args
        self.assertEqual(args[1], {"status": _STATUS_ID})
        self.assertIsNone(kwargs["find_parent"])

    async def test_namespace_alone_is_enough_and_finds_the_parent_in_that_namespace(self) -> None:
        seen: list[str] = []
        rest = _containing((_PREFIX_ID, "203.0.113.0/24"), ("x", "203.0.0.0/16"), seen=seen)
        out, common = await _run(
            {"nautobot_source_id": "s", "ip_id": _IP_ID, "namespace": "Lab"},
            _context(_device("a")),
            rest=rest,
        )
        self.assertIn("a", out["success"].devices)
        args, kwargs = common.update_ip_address.call_args
        self.assertEqual(args[1], {})
        # The most specific prefix of the target namespace wins.
        self.assertEqual(await kwargs["find_parent"]("203.0.113.5"), _PREFIX_ID)
        self.assertIn(f"namespace={_NS_ID}", seen[0])
        self.assertIn("contains=203.0.113.5", seen[0])

    async def test_namespace_without_a_containing_prefix_fails_the_device(self) -> None:
        common = MagicMock()
        common.update_ip_address = AsyncMock(
            side_effect=not_found("prefix_not_found", "No prefix contains 203.0.113.5")
        )
        out, _ = await _run(_config(namespace="Lab"), _context(_device("a")), common=common)
        error = out["failure"].devices["a"].errors[0]
        self.assertEqual(error.code, "prefix_not_found")
        self.assertIsNotNone(error.failure)

    async def test_ip_id_and_values_from_attributes(self) -> None:
        dev = _device("a", attribute_bags={"custom": {"ip_id": _IP_ID, "dns": "a.example.org"}})
        out, common = await _run(
            _config(ip_id="{custom.ip_id}", dns_name="{custom.dns}"), _context(dev)
        )
        self.assertIn("a", out["success"].devices)
        args = common.update_ip_address.call_args.args
        self.assertEqual(args[0], _IP_ID)
        self.assertEqual(args[1]["dns_name"], "a.example.org")

    async def test_lookups_resolved_once_for_all_devices(self) -> None:
        out, common = await _run(
            _config(role="Secondary", namespace="Global"),
            _context(_device("a"), _device("b"), _device("c")),
        )
        self.assertEqual(len(out["success"].devices), 3)
        self.assertEqual(common.resolve_status_id.call_count, 1)
        self.assertEqual(common.resolve_role_id_for_content_type.call_count, 1)
        self.assertEqual(common.resolve_namespace_id.call_count, 1)

    async def test_unchanged_ip_succeeds_and_is_counted(self) -> None:
        common = MagicMock()
        common.update_ip_address = AsyncMock(return_value=False)
        out, _ = await _run(_config(), _context(_device("a")), common=common)
        self.assertIn("a", out["success"].devices)
        counts = out["success"].metadata["n1.update_ip_counts"]
        self.assertEqual(counts["unchanged"], 1)
        self.assertEqual(counts["updated"], 0)

    async def test_no_devices_returns_empty_outcomes(self) -> None:
        out, common = await _run(_config(), _context())
        self.assertEqual((out["success"].devices, out["failure"].devices), ({}, {}))
        common.update_ip_address.assert_not_awaited()

    async def test_invalid_ip_id_fails_device_without_writing(self) -> None:
        out, common = await _run(_config(ip_id="10.0.0.1"), _context(_device("a")))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "ip_id_invalid")
        common.update_ip_address.assert_not_awaited()

    async def test_unresolved_expression_fails_device(self) -> None:
        out, _ = await _run(_config(ip_id="{custom.missing}"), _context(_device("a")))
        error = out["failure"].devices["a"].errors[0]
        self.assertEqual(error.code, "ip_id_unresolved")
        self.assertIsNotNone(error.failure)

    async def test_invalid_type_fails_device(self) -> None:
        out, common = await _run(_config(type="network"), _context(_device("a")))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "type_invalid")
        common.update_ip_address.assert_not_awaited()

    async def test_unknown_role_fails_device(self) -> None:
        common = MagicMock()
        common.resolve_role_id_for_content_type = AsyncMock(return_value=None)
        out, _ = await _run(_config(role="Nope"), _context(_device("a")), common=common)
        error = out["failure"].devices["a"].errors[0]
        self.assertEqual(error.code, "role_not_found")
        self.assertNotIn("Nope", error.message)

    async def test_unknown_status_fails_device(self) -> None:
        common = MagicMock()
        common.resolve_status_id = AsyncMock(side_effect=ValueError("Status 'x' not found"))
        out, _ = await _run(_config(status="Secret-Name"), _context(_device("a")), common=common)
        error = out["failure"].devices["a"].errors[0]
        self.assertEqual(error.code, "status_not_found")
        self.assertNotIn("Secret-Name", error.message)
        self.assertNotIn("Status 'x'", error.message)

    async def test_unknown_namespace_fails_device(self) -> None:
        common = MagicMock()
        common.resolve_namespace_id = AsyncMock(side_effect=ValueError("namespace not found"))
        out, _ = await _run(_config(namespace="Nope"), _context(_device("a")), common=common)
        error = out["failure"].devices["a"].errors[0]
        self.assertEqual(error.code, "namespace_not_found")
        self.assertNotIn("Nope", error.message)

    async def test_missing_ip_fails_device_with_not_found(self) -> None:
        common = MagicMock()
        common.update_ip_address = AsyncMock(side_effect=NautobotNotFoundError("gone"))
        out, _ = await _run(_config(), _context(_device("a")), common=common)
        error = out["failure"].devices["a"].errors[0]
        self.assertEqual(error.code, "ip_not_found")
        self.assertEqual(out["failure"].devices["a"].status, DeviceStatus.FAILED)

    async def test_nautobot_refusal_fails_device_without_raw_text(self) -> None:
        common = MagicMock()
        common.update_ip_address = AsyncMock(
            side_effect=NautobotAPIError("secret-ish body", http_status=400)
        )
        out, _ = await _run(_config(namespace="Other"), _context(_device("a")), common=common)
        error = out["failure"].devices["a"].errors[0]
        self.assertNotIn("secret-ish", error.message)
        self.assertIsNotNone(error.failure)

    async def test_sealed_secret_is_refused(self) -> None:
        def resolve(*, field_key: str, raw_value: str, **_: Any) -> str:
            return REDACTED_PLACEHOLDER if field_key == "description" else raw_value

        with patch.object(mod, "resolve_update_field_expression", side_effect=resolve):
            out, common = await _run(_config(description="{x.y}"), _context(_device("a")))
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "description_is_secret")
        common.update_ip_address.assert_not_awaited()

    async def test_devices_split_between_outcomes(self) -> None:
        good = _device("a", attribute_bags={"custom": {"ip_id": _IP_ID}})
        bad = _device("b")
        out, _ = await _run(_config(ip_id="{custom.ip_id}"), _context(good, bad))
        self.assertEqual(list(out["success"].devices), ["a"])
        self.assertEqual(list(out["failure"].devices), ["b"])

    async def test_empty_attribute_fails_device_as_unresolved(self) -> None:
        dev = _device("a", attribute_bags={"custom": {"d": ""}})
        out, common = await _run(
            {"nautobot_source_id": "s", "ip_id": _IP_ID, "description": "{custom.d}"},
            _context(dev),
        )
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "description_unresolved")
        common.update_ip_address.assert_not_awaited()

    async def test_every_field_resolving_to_empty_text_fails_device(self) -> None:
        out, common = await _run(
            {
                "nautobot_source_id": "s",
                "ip_id": _IP_ID,
                "description": "{custom.d | default('')}",
            },
            _context(_device("a")),
        )
        self.assertEqual(out["failure"].devices["a"].errors[0].code, "nothing_to_update")
        common.update_ip_address.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
