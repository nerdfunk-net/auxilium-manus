"""Tests for workflow_steps/get_nautobot_attributes/executor.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
)
from workflow_steps.get_nautobot_attributes import executor as mod
from workflow_steps.get_nautobot_attributes.executor import (
    _bind_nautobot,
    _build_outcomes,
    _fail_device,
    _fetch_device,
    _parse_config,
    _partition_device_results,
    execute,
)


def _device(did: str) -> DeviceContext:
    return DeviceContext(
        id=did, name=did, hostname=did, primary_ip4="10.0.0.1",
        capabilities={Capability.IDENTITY}, status=DeviceStatus.OK,
    )


class ParseConfigTests(unittest.TestCase):
    def test_missing_source_id_raises(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config({})

    def test_parses_source_id_and_attributes(self) -> None:
        cfg = _parse_config({"nautobot_source_id": " src-1 ", "list_of_attributes": ["tags"]})
        self.assertEqual(cfg.source_id, "src-1")
        self.assertEqual(cfg.list_of_attributes, ["tags"])


class HelperTests(unittest.TestCase):
    def test_fail_device_marks_failed(self) -> None:
        did, failed, ok = _fail_device(
            device=_device("d1"), device_id="d1", node_id="n", code="c", message="m"
        )
        self.assertEqual((did, ok), ("d1", False))
        self.assertEqual(failed.status, DeviceStatus.FAILED)

    def test_partition_and_outcomes(self) -> None:
        d = MagicMock()
        ok, failed = _partition_device_results([("a", d, True), ("b", d, False)])
        self.assertEqual((list(ok), list(failed)), (["a"], ["b"]))
        ctx = WorkflowContext(run_id="r", workflow_id="w", devices={})
        outs = _build_outcomes(ctx, {"a": d}, {"b": d})
        self.assertEqual([o.name for o in outs], ["success", "failure"])
        self.assertEqual([o.name for o in _build_outcomes(ctx, {"a": d}, {})], ["success"])


class BindNautobotTests(unittest.TestCase):
    def test_no_db_session_raises(self) -> None:
        run = MagicMock()
        with patch.object(mod, "object_session", return_value=None):
            with self.assertRaises(RuntimeError):
                _bind_nautobot(run, "src-1")

    def test_resolver_error_propagates(self) -> None:
        run = MagicMock()
        with (
            patch.object(mod, "object_session", return_value=MagicMock()),
            patch.object(
                mod,
                "resolve_nautobot_credentials",
                side_effect=ValueError("get-nautobot-attributes: boom"),
            ),
        ):
            with self.assertRaises(ValueError):
                _bind_nautobot(run, "src-1")

    def test_valid_source_builds_credentials(self) -> None:
        run = MagicMock()
        creds = MagicMock(url="https://nb")
        with (
            patch.object(mod, "object_session", return_value=MagicMock()),
            patch.object(mod, "resolve_nautobot_credentials", return_value=creds),
            patch.object(mod.service_factory, "get_nautobot_app_service", return_value="svc"),
        ):
            resolved_creds, svc = _bind_nautobot(run, "src-1")
        self.assertIs(resolved_creds, creds)
        self.assertEqual(svc, "svc")


class FetchDeviceTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_device_dict(self) -> None:
        svc = MagicMock()
        svc.graphql_query = AsyncMock(return_value={"data": {"device": {"id": "x"}}})
        out = await _fetch_device(svc, MagicMock(), "x", {})
        self.assertEqual(out, {"id": "x"})

    async def test_returns_none_when_device_missing(self) -> None:
        svc = MagicMock()
        svc.graphql_query = AsyncMock(return_value={"data": {"device": None}, "errors": ["e"]})
        self.assertIsNone(await _fetch_device(svc, MagicMock(), "x", {}))


def _run() -> MagicMock:
    run = MagicMock()
    run.id = 1
    return run


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_devices_returns_success(self) -> None:
        outcomes = await execute(
            config={"nautobot_source_id": "s"},
            context=WorkflowContext(run_id="r", workflow_id="w", devices={}),
            run=_run(), artifact_service=MagicMock(), node_id="n", device_sessions=MagicMock(),
        )
        self.assertEqual([o.name for o in outcomes], ["success"])

    async def test_enriches_device_with_nautobot_bag(self) -> None:
        svc = MagicMock()
        svc.graphql_query = AsyncMock(
            return_value={"data": {"device": {
                "id": "nb-1", "name": "r1",
                "platform": {"name": "ios", "network_driver": "ios"},
                "_custom_field_data": {"site": "NYC"},
            }}}
        )
        ctx = WorkflowContext(run_id="r", workflow_id="w", devices={"d1": _device("d1")})
        with (
            patch.object(mod, "_bind_nautobot", return_value=(MagicMock(), svc)),
            patch.object(mod, "resolve_nautobot_device_id", AsyncMock(return_value="nb-1")),
        ):
            outcomes = await execute(
                config={"nautobot_source_id": "s"}, context=ctx, run=_run(),
                artifact_service=MagicMock(), node_id="n", device_sessions=MagicMock(),
            )
        enriched = next(o for o in outcomes if o.name == "success").context.devices["d1"]
        self.assertEqual(enriched.attribute_bags["nautobot"]["custom_fields"], {"site": "NYC"})
        self.assertEqual(enriched.platform, "ios")
        self.assertIn(Capability.ATTRIBUTES, enriched.capabilities)

    async def test_unresolved_device_routes_to_failure(self) -> None:
        ctx = WorkflowContext(run_id="r", workflow_id="w", devices={"d1": _device("d1")})
        with (
            patch.object(mod, "_bind_nautobot", return_value=(MagicMock(), MagicMock())),
            patch.object(mod, "resolve_nautobot_device_id", AsyncMock(return_value=None)),
        ):
            outcomes = await execute(
                config={"nautobot_source_id": "s"}, context=ctx, run=_run(),
                artifact_service=MagicMock(), node_id="n", device_sessions=MagicMock(),
            )
        by_name = {o.name: o for o in outcomes}
        failed = by_name["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[-1].code, "not_found")

    async def test_resolver_exception_routes_to_failure(self) -> None:
        ctx = WorkflowContext(run_id="r", workflow_id="w", devices={"d1": _device("d1")})
        with (
            patch.object(mod, "_bind_nautobot", return_value=(MagicMock(), MagicMock())),
            patch.object(
                mod, "resolve_nautobot_device_id", AsyncMock(side_effect=RuntimeError("boom"))
            ),
        ):
            outcomes = await execute(
                config={"nautobot_source_id": "s"}, context=ctx, run=_run(),
                artifact_service=MagicMock(), node_id="n", device_sessions=MagicMock(),
            )
        failed = {o.name: o for o in outcomes}["failure"].context.devices["d1"]
        self.assertEqual(failed.errors[-1].code, "runtimeerror")


if __name__ == "__main__":
    unittest.main()
