"""Executor-level tests for workflow_steps/update_nautobot_device/executor.py
(the pure helpers are covered in test_update_nautobot_device_helpers.py)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from workflow_steps.update_nautobot_device import executor as mod
from workflow_steps.update_nautobot_device.executor import (
    _apply_update_result,
    _build_update_service,
    _fail_device,
    _resolve_device_identifier,
    _strip_empty,
    _update_one_device,
    execute,
)

_CFG = {
    "nautobot_source_id": "src-1",
    "update_fields": {"name": {"enabled": True, "value": "new"}},
}


def _device(did: str = "d1") -> DeviceContext:
    return DeviceContext(id=did, name=did, hostname=did, primary_ip4="10.0.0.1")


class StripEmptyTests(unittest.TestCase):
    def test_strips_and_nulls_blank_strings(self) -> None:
        self.assertIsNone(_strip_empty("   "))
        self.assertEqual(_strip_empty("  x "), "x")
        self.assertEqual(_strip_empty(5), 5)


class ResolveDeviceIdentifierTests(unittest.TestCase):
    def test_explicit_mode_uses_configured_id_and_name(self) -> None:
        ident = _resolve_device_identifier(
            config={"device_identifier": {"mode": "explicit", "id": " abc ", "name": ""}},
            device=_device(),
            nautobot_device_id=None,
        )
        self.assertEqual(ident, {"id": "abc"})

    def test_from_context_prefers_resolved_nautobot_id(self) -> None:
        ident = _resolve_device_identifier(
            config={}, device=_device(), nautobot_device_id="nb-1"
        )
        self.assertEqual(ident, {"id": "nb-1"})

    def test_from_context_falls_back_to_name_then_ip(self) -> None:
        by_name = _resolve_device_identifier(
            config={}, device=_device("r1"), nautobot_device_id=None
        )
        self.assertEqual(by_name, {"name": "r1"})
        no_name = DeviceContext(id="d1", name="", hostname="d1", primary_ip4="10.0.0.9")
        by_ip = _resolve_device_identifier(config={}, device=no_name, nautobot_device_id=None)
        self.assertEqual(by_ip, {"ip_address": "10.0.0.9"})

    def test_explicit_mode_without_values_falls_through_to_context(self) -> None:
        ident = _resolve_device_identifier(
            config={"device_identifier": {"mode": "explicit"}},
            device=_device("r1"),
            nautobot_device_id=None,
        )
        self.assertEqual(ident, {"name": "r1"})


class BuildUpdateServiceTests(unittest.TestCase):
    def _repo(self, value):
        repo = MagicMock()
        repo.get_by_key.return_value = MagicMock(value=value) if value is not None else None
        return repo

    def test_missing_setting_raises(self) -> None:
        with patch.object(mod, "SettingsRepository", return_value=self._repo(None)):
            with self.assertRaises(ValueError):
                _build_update_service(MagicMock(), "src-1")

    def test_missing_url_token_raises(self) -> None:
        with patch.object(mod, "SettingsRepository", return_value=self._repo({"url": ""})):
            with self.assertRaises(ValueError):
                _build_update_service(MagicMock(), "src-1")

    def test_valid_setting_returns_wired_services(self) -> None:
        with (
            patch.object(
                mod, "SettingsRepository",
                return_value=self._repo({"url": "https://nb", "token": "t"}),
            ),
            patch.object(mod.service_factory, "get_nautobot_app_service", return_value="svc"),
        ):
            svc, creds, update_service = _build_update_service(MagicMock(), "src-1")
        self.assertEqual(svc, "svc")
        self.assertEqual(creds.url, "https://nb")
        self.assertIsNotNone(update_service)


class FailAndApplyTests(unittest.TestCase):
    def test_fail_device_with_none_builds_placeholder(self) -> None:
        key, dev, ok, rid = _fail_device(
            device_key="explicit", device=None, node_id="n", exc=RuntimeError("boom")
        )
        self.assertEqual((key, ok, rid), ("explicit", False, None))
        self.assertEqual(dev.status, DeviceStatus.FAILED)
        self.assertEqual(dev.errors[0].code, "runtimeerror")

    def test_fail_device_with_device_appends_error(self) -> None:
        _, dev, ok, _ = _fail_device(
            device_key="d1", device=_device(), node_id="n", code="x", message="m"
        )
        self.assertFalse(ok)
        self.assertEqual(dev.errors[-1].code, "x")

    def test_apply_update_result_with_none_device(self) -> None:
        key, dev, ok, rid = _apply_update_result(
            device_key="explicit", device=None,
            result={"device_id": "nb-9", "device_name": "router9"},
        )
        self.assertEqual((ok, rid), (True, "nb-9"))
        self.assertEqual(dev.name, "router9")
        self.assertEqual(dev.status, DeviceStatus.OK)

    def test_apply_update_result_with_device(self) -> None:
        _, dev, ok, rid = _apply_update_result(
            device_key="d1", device=_device("d1"),
            result={"device_id": "nb-1", "device_name": "renamed"},
        )
        self.assertEqual((ok, rid), (True, "nb-1"))
        self.assertEqual(dev.name, "renamed")
        self.assertEqual(dev.source, "nautobot")


class UpdateOneDeviceTests(unittest.IsolatedAsyncioTestCase):
    def _parsed(self):
        return mod._parse_config(_CFG)

    async def _run_one(self, *, resolve_id, update_result=None, update_exc=None):
        update_service = MagicMock()
        if update_exc is not None:
            update_service.update_device = AsyncMock(side_effect=update_exc)
        else:
            update_service.update_device = AsyncMock(return_value=update_result)
        with (
            patch.object(mod, "resolve_nautobot_device_id", AsyncMock(return_value=resolve_id)),
            patch.object(mod, "build_resolved_update_data", return_value={"name": "new"}),
        ):
            return await _update_one_device(
                device_key="d1", device=_device("d1"), config=_CFG,
                context=WorkflowContext(run_id="r", workflow_id="w", devices={}),
                node_id="n", nautobot_service=MagicMock(), credentials=MagicMock(),
                update_service=update_service, parsed=self._parsed(),
            )

    async def test_unresolved_device_fails(self) -> None:
        key, dev, ok, _ = await self._run_one(resolve_id=None)
        self.assertFalse(ok)
        self.assertEqual(dev.errors[-1].code, "not_found")

    async def test_success(self) -> None:
        key, dev, ok, rid = await self._run_one(
            resolve_id="nb-1",
            update_result={"device_id": "nb-1", "device_name": "r1", "interfaces_failed": 0},
        )
        self.assertTrue(ok)
        self.assertEqual(rid, "nb-1")

    async def test_interface_failure_raises_and_is_caught(self) -> None:
        key, dev, ok, _ = await self._run_one(
            resolve_id="nb-1",
            update_result={"device_id": "nb-1", "device_name": "r1", "interfaces_failed": 2},
        )
        self.assertFalse(ok)
        self.assertEqual(dev.errors[-1].code, "runtimeerror")

    async def test_update_exception_is_caught(self) -> None:
        key, dev, ok, _ = await self._run_one(
            resolve_id="nb-1", update_exc=ValueError("bad payload")
        )
        self.assertFalse(ok)
        self.assertEqual(dev.errors[-1].code, "valueerror")


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_db_session_raises(self) -> None:
        with patch.object(mod, "object_session", return_value=None):
            with self.assertRaises(RuntimeError):
                await execute(
                    config=_CFG,
                    context=WorkflowContext(
                        run_id="r", workflow_id="w", devices={"d1": _device("d1")}
                    ),
                    run=MagicMock(), artifact_service=MagicMock(),
                    node_id="n", device_sessions=MagicMock(),
                )

    async def test_full_success_path(self) -> None:
        update_service = MagicMock()
        update_service.update_device = AsyncMock(
            return_value={"device_id": "nb-1", "device_name": "r1", "interfaces_failed": 0}
        )
        run = MagicMock()
        run.id = 1
        ctx = WorkflowContext(run_id="r", workflow_id="w", devices={"d1": _device("d1")})
        with (
            patch.object(mod, "object_session", return_value=MagicMock()),
            patch.object(
                mod, "_build_update_service",
                return_value=(MagicMock(), MagicMock(), update_service),
            ),
            patch.object(mod, "resolve_nautobot_device_id", AsyncMock(return_value="nb-1")),
            patch.object(mod, "build_resolved_update_data", return_value={"name": "new"}),
        ):
            outcomes = await execute(
                config=_CFG, context=ctx, run=run, artifact_service=MagicMock(),
                node_id="n", device_sessions=MagicMock(),
            )
        success = next(o for o in outcomes if o.name == "success")
        self.assertIn("d1", success.context.devices)
        self.assertEqual(success.context.devices["d1"].source, "nautobot")


if __name__ == "__main__":
    unittest.main()
