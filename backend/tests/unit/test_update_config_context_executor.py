"""Executor-level tests for workflow_steps/update_config_context/executor.py."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import DeviceContext, DeviceStatus, WorkflowContext
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.update_config_context import executor as mod
from workflow_steps.update_config_context.executor import (
    _apply_mode,
    _explicit_device_context,
    _parse_config,
    _resolve_value,
    _update_one_device,
    execute,
)


def _device(did: str = "d1", **bags: dict) -> DeviceContext:
    device = DeviceContext(id=did, name=did, hostname=did, primary_ip4="10.0.0.1")
    if bags:
        device = device.model_copy(update={"attribute_bags": bags})
    return device


def _attribute_config(path: str, *, mode: str = "write", cfg_path: str = "") -> dict:
    return {
        "nautobot_source_id": "src-1",
        "mode": mode,
        "path": cfg_path,
        "value_source": {"type": "attribute", "attribute_path": path},
    }


class ParseConfigTests(unittest.TestCase):
    def test_requires_source_id(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config({})

    def test_rejects_unknown_mode(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config({"nautobot_source_id": "s", "mode": "delete"})

    def test_update_requires_path(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config({"nautobot_source_id": "s", "mode": "update"})

    def test_append_does_not_require_path(self) -> None:
        parsed = _parse_config(
            {
                "nautobot_source_id": "s",
                "mode": "append",
                "value_source": {"type": "attribute", "attribute_path": "tacacs"},
            }
        )
        self.assertEqual(parsed.path, "")

    def test_write_mode_does_not_require_path(self) -> None:
        parsed = _parse_config(
            {
                "nautobot_source_id": "s",
                "mode": "write",
                "value_source": {"type": "attribute", "attribute_path": "tacacs"},
            }
        )
        self.assertEqual(parsed.mode, "write")

    def test_attribute_source_requires_attribute_path(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config(
                {"nautobot_source_id": "s", "value_source": {"type": "attribute"}}
            )

    def test_template_source_requires_template_id(self) -> None:
        with self.assertRaises(ValueError):
            _parse_config({"nautobot_source_id": "s", "value_source": {"type": "template"}})

    def test_template_source_parses_int(self) -> None:
        parsed = _parse_config(
            {
                "nautobot_source_id": "s",
                "value_source": {"type": "template", "template_id": "7"},
            }
        )
        self.assertEqual(parsed.template_id, 7)


class ExplicitDeviceContextTests(unittest.TestCase):
    def test_uses_id_when_given(self) -> None:
        device = _explicit_device_context({"id": "abc-123"})
        self.assertEqual(device.id, "abc-123")
        self.assertEqual(device.source, "nautobot")

    def test_falls_back_to_name(self) -> None:
        device = _explicit_device_context({"name": "router1"})
        self.assertEqual(device.name, "router1")


class ResolveValueTests(unittest.TestCase):
    def test_attribute_source_returns_raw_value(self) -> None:
        device = _device(tacacs={"shared_secret": "plain-key"})
        parsed = _parse_config(_attribute_config("tacacs.shared_secret"))
        value = _resolve_value(parsed=parsed, device=device, run_id="r", workflow_id="w")
        self.assertEqual(value, "plain-key")

    def test_attribute_source_unwraps_sealed_secret(self) -> None:
        device = _device(tacacs={"shared_secret": seal_secret("s3cr3t")})
        parsed = _parse_config(_attribute_config("tacacs.shared_secret"))
        value = _resolve_value(parsed=parsed, device=device, run_id="r", workflow_id="w")
        self.assertEqual(value, "s3cr3t")

    def test_attribute_source_can_return_structured_value(self) -> None:
        device = _device(
            credentials={"list": [{"username": "noc", "password": "pw"}]}
        )
        parsed = _parse_config(_attribute_config("credentials.list"))
        value = _resolve_value(parsed=parsed, device=device, run_id="r", workflow_id="w")
        self.assertEqual(value, [{"username": "noc", "password": "pw"}])

    def test_attribute_source_without_device_raises(self) -> None:
        parsed = _parse_config(_attribute_config("tacacs.shared_secret"))
        with self.assertRaises(ValueError):
            _resolve_value(parsed=parsed, device=None, run_id="r", workflow_id="w")

    def test_template_source_parses_json_output(self) -> None:
        config = {
            "nautobot_source_id": "s",
            "value_source": {"type": "template", "template_id": 1},
        }
        parsed = _parse_config(config)
        with (
            patch.object(mod, "load_stored_template", return_value='{"shared_secret": "x"}'),
            patch.object(mod, "render_jinja_template", return_value='{"shared_secret": "x"}'),
        ):
            value = _resolve_value(parsed=parsed, device=_device(), run_id="r", workflow_id="w")
        self.assertEqual(value, {"shared_secret": "x"})

    def test_template_source_falls_back_to_plain_string(self) -> None:
        config = {
            "nautobot_source_id": "s",
            "value_source": {"type": "template", "template_id": 1},
        }
        parsed = _parse_config(config)
        with (
            patch.object(mod, "load_stored_template", return_value="not-json"),
            patch.object(mod, "render_jinja_template", return_value="not-json"),
        ):
            value = _resolve_value(parsed=parsed, device=_device(), run_id="r", workflow_id="w")
        self.assertEqual(value, "not-json")


class ApplyModeTests(unittest.IsolatedAsyncioTestCase):
    async def test_write_requires_dict_value(self) -> None:
        parsed = _parse_config(_attribute_config("tacacs", mode="write"))
        update_service = MagicMock()
        with self.assertRaises(ValueError):
            await _apply_mode(
                update_service=update_service, device_id="nb-1", parsed=parsed, value="not-a-dict"
            )

    async def test_write_patches_directly_without_get(self) -> None:
        parsed = _parse_config(_attribute_config("tacacs", mode="write"))
        update_service = MagicMock()
        update_service.set_local_config_context = AsyncMock()
        update_service.get_local_config_context = AsyncMock()
        await _apply_mode(
            update_service=update_service,
            device_id="nb-1",
            parsed=parsed,
            value={"tacacs": {"shared_secret": "x"}},
        )
        update_service.get_local_config_context.assert_not_awaited()
        update_service.set_local_config_context.assert_awaited_once_with(
            "nb-1", {"tacacs": {"shared_secret": "x"}}
        )

    async def test_update_replaces_leaf_and_preserves_siblings(self) -> None:
        parsed = _parse_config(
            _attribute_config("x", mode="update", cfg_path="credentials.0.password")
        )
        update_service = MagicMock()
        update_service.get_local_config_context = AsyncMock(
            return_value={"credentials": [{"username": "noc", "password": "old"}]}
        )
        update_service.set_local_config_context = AsyncMock()
        await _apply_mode(
            update_service=update_service, device_id="nb-1", parsed=parsed, value="new"
        )
        new_doc = update_service.set_local_config_context.call_args.args[1]
        self.assertEqual(new_doc["credentials"][0]["password"], "new")
        self.assertEqual(new_doc["credentials"][0]["username"], "noc")

    async def test_append_merges_into_existing_object(self) -> None:
        parsed = _parse_config(
            _attribute_config("x", mode="append", cfg_path="tacacs")
        )
        update_service = MagicMock()
        update_service.get_local_config_context = AsyncMock(
            return_value={"credentials": [{"username": "noc"}], "tacacs": {"port": 49}}
        )
        update_service.set_local_config_context = AsyncMock()
        await _apply_mode(
            update_service=update_service,
            device_id="nb-1",
            parsed=parsed,
            value={"shared_secret": "newkey"},
        )
        new_doc = update_service.set_local_config_context.call_args.args[1]
        self.assertEqual(new_doc["tacacs"], {"port": 49, "shared_secret": "newkey"})
        self.assertEqual(new_doc["credentials"], [{"username": "noc"}])

    async def test_append_sets_new_root_key_when_absent(self) -> None:
        parsed = _parse_config(
            _attribute_config("x", mode="append", cfg_path="tacacs")
        )
        update_service = MagicMock()
        update_service.get_local_config_context = AsyncMock(
            return_value={"credentials": [{"username": "noc"}]}
        )
        update_service.set_local_config_context = AsyncMock()
        await _apply_mode(
            update_service=update_service,
            device_id="nb-1",
            parsed=parsed,
            value={"shared_secret": "newkey"},
        )
        new_doc = update_service.set_local_config_context.call_args.args[1]
        self.assertEqual(new_doc["tacacs"], {"shared_secret": "newkey"})
        self.assertEqual(new_doc["credentials"], [{"username": "noc"}])

    async def test_append_with_empty_path_merges_into_root(self) -> None:
        parsed = _parse_config(_attribute_config("x", mode="append", cfg_path=""))
        update_service = MagicMock()
        update_service.get_local_config_context = AsyncMock(
            return_value={"credentials": [{"username": "noc"}]}
        )
        update_service.set_local_config_context = AsyncMock()
        await _apply_mode(
            update_service=update_service,
            device_id="nb-1",
            parsed=parsed,
            value={"xxx": {"key": "value"}},
        )
        new_doc = update_service.set_local_config_context.call_args.args[1]
        self.assertEqual(
            new_doc, {"credentials": [{"username": "noc"}], "xxx": {"key": "value"}}
        )

    async def test_append_with_empty_path_requires_dict_value(self) -> None:
        parsed = _parse_config(_attribute_config("x", mode="append", cfg_path=""))
        update_service = MagicMock()
        update_service.get_local_config_context = AsyncMock(return_value={})
        with self.assertRaises(ValueError):
            await _apply_mode(
                update_service=update_service,
                device_id="nb-1",
                parsed=parsed,
                value="not-a-dict",
            )


class UpdateOneDeviceTests(unittest.IsolatedAsyncioTestCase):
    async def test_unresolved_device_fails(self) -> None:
        parsed = _parse_config(_attribute_config("tacacs", mode="write"))
        update_service = MagicMock()
        with patch.object(mod, "resolve_nautobot_device_id", AsyncMock(return_value=None)):
            key, dev, ok = await _update_one_device(
                device_key="d1",
                device=_device("d1"),
                parsed=parsed,
                context=WorkflowContext(run_id="r", workflow_id="w", devices={}),
                node_id="n",
                nautobot_service=MagicMock(),
                credentials=MagicMock(),
                update_service=update_service,
            )
        self.assertFalse(ok)
        self.assertEqual(dev.errors[-1].code, "not_found")

    async def test_success_marks_device_ok(self) -> None:
        parsed = _parse_config(_attribute_config("tacacs.shared_secret", mode="write"))
        update_service = MagicMock()
        update_service.set_local_config_context = AsyncMock()
        device = _device("d1", tacacs={"shared_secret": {"port": 49}})
        with patch.object(mod, "resolve_nautobot_device_id", AsyncMock(return_value="nb-1")):
            key, dev, ok = await _update_one_device(
                device_key="d1",
                device=device,
                parsed=parsed,
                context=WorkflowContext(run_id="r", workflow_id="w", devices={}),
                node_id="n",
                nautobot_service=MagicMock(),
                credentials=MagicMock(),
                update_service=update_service,
            )
        self.assertTrue(ok)
        self.assertEqual(dev.status, DeviceStatus.OK)

    async def test_apply_exception_is_caught(self) -> None:
        parsed = _parse_config(_attribute_config("tacacs", mode="write"))
        update_service = MagicMock()
        update_service.set_local_config_context = AsyncMock(side_effect=RuntimeError("boom"))
        device = _device("d1", tacacs={"shared_secret": {"port": 49}})
        with patch.object(mod, "resolve_nautobot_device_id", AsyncMock(return_value="nb-1")):
            key, dev, ok = await _update_one_device(
                device_key="d1",
                device=device,
                parsed=parsed,
                context=WorkflowContext(run_id="r", workflow_id="w", devices={}),
                node_id="n",
                nautobot_service=MagicMock(),
                credentials=MagicMock(),
                update_service=update_service,
            )
        self.assertFalse(ok)


class ExecuteTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_db_session_raises(self) -> None:
        with patch.object(mod, "object_session", return_value=None):
            with self.assertRaises(RuntimeError):
                await execute(
                    config=_attribute_config("tacacs", mode="write"),
                    context=WorkflowContext(
                        run_id="r", workflow_id="w", devices={"d1": _device("d1")}
                    ),
                    run=MagicMock(),
                    artifact_service=MagicMock(),
                    node_id="n",
                    device_sessions=MagicMock(),
                )

    async def test_full_success_path(self) -> None:
        update_service = MagicMock()
        update_service.set_local_config_context = AsyncMock()
        run = MagicMock()
        run.id = 1
        device = _device("d1", tacacs={"shared_secret": {"port": 49}})
        ctx = WorkflowContext(run_id="r", workflow_id="w", devices={"d1": device})
        with (
            patch.object(mod, "object_session", return_value=MagicMock()),
            patch.object(
                mod,
                "_build_update_service",
                return_value=(MagicMock(), MagicMock(), update_service),
            ),
            patch.object(mod, "resolve_nautobot_device_id", AsyncMock(return_value="nb-1")),
        ):
            outcomes = await execute(
                config=_attribute_config("tacacs.shared_secret", mode="write"),
                context=ctx,
                run=run,
                artifact_service=MagicMock(),
                node_id="n",
                device_sessions=MagicMock(),
            )
        success = next(o for o in outcomes if o.name == "success")
        self.assertIn("d1", success.context.devices)
        self.assertEqual(success.context.devices["d1"].status, DeviceStatus.OK)
        update_service.set_local_config_context.assert_awaited_once_with(
            "nb-1", {"port": 49}
        )


if __name__ == "__main__":
    unittest.main()
