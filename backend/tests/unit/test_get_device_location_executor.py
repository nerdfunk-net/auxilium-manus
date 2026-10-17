"""Tests for workflow_steps/get_device_location/executor.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from workflow_steps.get_device_location import executor as mod
from workflow_steps.get_device_location.executor import _parse_config, execute

_ROOM = {
    "name": "Room A",
    "location_type": {"name": "Room"},
    "parent": {
        "name": "City A",
        "location_type": {"name": "City"},
        "parent": None,
    },
}


def _device(did: str, bags: dict | None = None) -> DeviceContext:
    return DeviceContext(
        id=did, name=did, hostname=did, primary_ip4="10.0.0.1",
        capabilities={Capability.IDENTITY}, status=DeviceStatus.OK,
        attribute_bags=bags or {},
    )


def _cfg(**extra: object) -> dict:
    return {"nautobot_source_id": "s", "location_type": "City", **extra}


async def _run_execute(config: dict, devices: dict, svc: MagicMock, resolver: AsyncMock):
    ctx = WorkflowContext(run_id="r", workflow_id="w", devices=devices)
    run = MagicMock()
    run.id = 1
    with (
        patch.object(mod, "_bind_nautobot", return_value=(MagicMock(), svc)),
        patch.object(mod, "resolve_nautobot_device_id", resolver),
    ):
        return await execute(
            config=config, context=ctx, run=run,
            artifact_service=MagicMock(), node_id="n", device_sessions=MagicMock(),
        )


def _svc(location: dict | None) -> MagicMock:
    svc = MagicMock()
    svc.graphql_query = AsyncMock(return_value={"data": {"device": {"location": location}}})
    return svc


class ParseConfigTests(unittest.TestCase):
    def test_defaults(self) -> None:
        cfg = _parse_config(_cfg())
        self.assertEqual(cfg.target_attribute, "custom.location")
        self.assertFalse(cfg.case_insensitive_lookup)

    def test_missing_source_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config({"location_type": "City"})

    def test_missing_location_type_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config({"nautobot_source_id": "s"})

    def test_bad_target_paths_raise(self) -> None:
        for bad in (
            "location", "device.name", "parsed.x", "run_input.x", "custom.",
            "name.city", "source.x", "custom.a..b", ".custom.x",
        ):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                _parse_config(_cfg(target_attribute=bad))


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_devices_returns_success(self) -> None:
        outs = await _run_execute(_cfg(), {}, MagicMock(), AsyncMock())
        self.assertEqual([o.name for o in outs], ["success"])

    async def test_writes_location_name_and_keeps_other_keys(self) -> None:
        dev = _device("d1", {"custom": {"keep": "1"}})
        outs = await _run_execute(_cfg(), {"d1": dev}, _svc(_ROOM), AsyncMock(return_value="nb-1"))
        out = next(o for o in outs if o.name == "success").context.devices["d1"]
        self.assertEqual(out.attribute_bags["custom"], {"keep": "1", "location": "City A"})
        self.assertEqual(dev.attribute_bags["custom"], {"keep": "1"})

    async def test_custom_target_attribute(self) -> None:
        outs = await _run_execute(
            _cfg(target_attribute="site.city"), {"d1": _device("d1")},
            _svc(_ROOM), AsyncMock(return_value="nb-1"),
        )
        out = next(o for o in outs if o.name == "success").context.devices["d1"]
        self.assertEqual(out.attribute_bags["site"]["city"], "City A")

    async def test_type_not_in_chain_fails_device(self) -> None:
        outs = await _run_execute(
            _cfg(location_type="Continent"), {"d1": _device("d1")},
            _svc(_ROOM), AsyncMock(return_value="nb-1"),
        )
        failed = {o.name: o for o in outs}["failure"].context.devices["d1"]
        self.assertEqual(failed.status, DeviceStatus.FAILED)
        self.assertEqual(failed.errors[-1].code, "location_type_not_found")
        self.assertIn("Room A (Room)", failed.errors[-1].message)

    async def test_nestable_type_twice_fails_ambiguous(self) -> None:
        nested = {
            "name": "Inner", "location_type": {"name": "Building"},
            "parent": {"name": "Outer", "location_type": {"name": "Building"}, "parent": None},
        }
        outs = await _run_execute(
            _cfg(location_type="Building"), {"d1": _device("d1")},
            _svc(nested), AsyncMock(return_value="nb-1"),
        )
        failed = {o.name: o for o in outs}["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[-1].code, "location_type_ambiguous")
        self.assertEqual(failed.errors[-1].failure.kind, "ambiguous_match")
        self.assertIn("Inner", failed.errors[-1].message)

    async def test_graphql_error_fails_device_without_leaking_text(self) -> None:
        svc = MagicMock()
        svc.graphql_query = AsyncMock(side_effect=RuntimeError("graphql_error: bad field"))
        outs = await _run_execute(
            _cfg(), {"d1": _device("d1")}, svc, AsyncMock(return_value="nb-1")
        )
        failed = {o.name: o for o in outs}["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[-1].code, "runtimeerror")
        self.assertNotIn("graphql", failed.errors[-1].message)

    async def test_strict_flag_passed(self) -> None:
        svc = _svc(_ROOM)
        await _run_execute(_cfg(), {"d1": _device("d1")}, svc, AsyncMock(return_value="nb-1"))
        self.assertTrue(svc.graphql_query.call_args.kwargs["strict"])

    async def test_device_without_location_fails(self) -> None:
        outs = await _run_execute(
            _cfg(), {"d1": _device("d1")}, _svc(None), AsyncMock(return_value="nb-1")
        )
        failed = {o.name: o for o in outs}["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[-1].code, "location_type_not_found")

    async def test_unknown_device_fails_not_found(self) -> None:
        outs = await _run_execute(
            _cfg(), {"d1": _device("d1")}, _svc(_ROOM), AsyncMock(return_value=None)
        )
        failed = {o.name: o for o in outs}["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[-1].code, "not_found")

    async def test_graphql_device_missing_fails_not_found(self) -> None:
        svc = MagicMock()
        svc.graphql_query = AsyncMock(return_value={"data": {"device": None}})
        outs = await _run_execute(_cfg(), {"d1": _device("d1")}, svc, AsyncMock(return_value="x"))
        failed = {o.name: o for o in outs}["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[-1].code, "not_found")

    async def test_exception_message_is_sanitised(self) -> None:
        outs = await _run_execute(
            _cfg(), {"d1": _device("d1")}, _svc(_ROOM),
            AsyncMock(side_effect=RuntimeError("secret sql")),
        )
        failed = {o.name: o for o in outs}["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[-1].message, "RuntimeError")

    async def test_partial_split(self) -> None:
        resolver = AsyncMock(side_effect=["nb-1", None])
        outs = await _run_execute(
            _cfg(), {"a": _device("a"), "b": _device("b")}, _svc(_ROOM), resolver
        )
        by = {o.name: o for o in outs}
        self.assertEqual(list(by["success"].context.devices), ["a"])
        self.assertEqual(list(by["failure"].context.devices), ["b"])

    async def test_case_insensitive_flag_forwarded(self) -> None:
        resolver = AsyncMock(return_value="nb-1")
        await _run_execute(
            _cfg(case_insensitive_lookup=True), {"d1": _device("d1")}, _svc(_ROOM), resolver
        )
        self.assertTrue(resolver.call_args.kwargs["case_insensitive"])


if __name__ == "__main__":
    unittest.main()
