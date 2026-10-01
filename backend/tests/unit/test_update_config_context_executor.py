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
    _render_path,
    _resolve_value,
    _update_one_device,
    execute,
)


def _device(did: str = "d1", **bags: dict) -> DeviceContext:
    device = DeviceContext(id=did, name=did, hostname=did, primary_ip4="10.0.0.1")
    if bags:
        device = device.model_copy(update={"attribute_bags": bags})
    return device


def _attribute_config(
    path: str, *, mode: str = "write", cfg_path: str = "", create_local: bool | None = None
) -> dict:
    config: dict = {
        "nautobot_source_id": "src-1",
        "mode": mode,
        "path": cfg_path,
        "value_source": {"type": "attribute", "attribute_path": path},
    }
    if create_local is not None:
        config["create_local_if_missing"] = create_local
    return config


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


_GLOBAL_CONTEXT = {
    "somethingelse": [{"xyz": "abc"}],
    "tacacs": [
        {"key": "mykey", "level": 7, "server": "tacacs-server", "address": "1.2.3.4"},
    ],
}
_TACACS_PATH = "tacacs[address=1.2.3.4].key"


def _seeding_service(*, local: dict, merged: dict | None = None) -> MagicMock:
    service = MagicMock()
    service.get_local_config_context = AsyncMock(return_value=local)
    service.get_config_context = AsyncMock(
        return_value=_GLOBAL_CONTEXT if merged is None else merged
    )
    service.set_local_config_context = AsyncMock()
    return service


class CreateLocalIfMissingParseTests(unittest.TestCase):
    def test_defaults_to_false(self) -> None:
        parsed = _parse_config(_attribute_config("x", mode="update", cfg_path=_TACACS_PATH))
        self.assertFalse(parsed.create_local_if_missing)

    def test_accepts_bool_and_truthy_strings(self) -> None:
        for raw, expected in ((True, True), ("true", True), ("no", False), (False, False)):
            parsed = _parse_config(
                _attribute_config("x", mode="update", cfg_path=_TACACS_PATH, create_local=raw)
            )
            self.assertEqual(parsed.create_local_if_missing, expected, raw)


class CreateLocalIfMissingTests(unittest.IsolatedAsyncioTestCase):
    async def _run(
        self,
        service: MagicMock,
        *,
        mode: str = "update",
        create_local: bool = True,
        cfg_path: str = _TACACS_PATH,
        value: object = "newkey",
    ) -> None:
        parsed = _parse_config(
            _attribute_config("x", mode=mode, cfg_path=cfg_path, create_local=create_local)
        )
        await _apply_mode(update_service=service, device_id="nb-1", parsed=parsed, value=value)

    async def test_null_local_context_is_seeded_from_global_in_one_patch(self) -> None:
        service = _seeding_service(local={})
        await self._run(service)
        service.set_local_config_context.assert_awaited_once()
        new_doc = service.set_local_config_context.call_args.args[1]
        self.assertEqual(
            new_doc,
            {
                "tacacs": [
                    {"key": "newkey", "level": 7, "server": "tacacs-server", "address": "1.2.3.4"}
                ]
            },
        )
        self.assertNotIn("somethingelse", new_doc)

    async def test_non_empty_local_without_the_key_keeps_its_other_keys(self) -> None:
        service = _seeding_service(local={"credentials": [{"username": "noc"}]})
        await self._run(service)
        new_doc = service.set_local_config_context.call_args.args[1]
        self.assertEqual(new_doc["credentials"], [{"username": "noc"}])
        self.assertEqual(new_doc["tacacs"][0]["key"], "newkey")

    async def test_local_with_the_key_is_updated_in_place_without_global_fetch(self) -> None:
        local = {"tacacs": [{"key": "old", "address": "1.2.3.4", "server": "local-srv"}]}
        service = _seeding_service(local=local)
        await self._run(service)
        service.get_config_context.assert_not_awaited()
        new_doc = service.set_local_config_context.call_args.args[1]
        self.assertEqual(
            new_doc["tacacs"], [{"key": "newkey", "address": "1.2.3.4", "server": "local-srv"}]
        )

    async def test_local_key_without_matching_item_fails_and_does_not_copy_global(self) -> None:
        local = {"tacacs": [{"key": "old", "address": "9.9.9.9"}]}
        service = _seeding_service(local=local)
        with self.assertRaisesRegex(ValueError, "no item"):
            await self._run(service)
        service.get_config_context.assert_not_awaited()
        service.set_local_config_context.assert_not_awaited()

    async def test_flag_off_keeps_existing_behaviour(self) -> None:
        service = _seeding_service(local={})
        with self.assertRaisesRegex(ValueError, "not a list"):
            await self._run(service, create_local=False)
        service.get_config_context.assert_not_awaited()
        service.set_local_config_context.assert_not_awaited()

    async def test_key_missing_in_global_too_falls_through(self) -> None:
        service = _seeding_service(local={}, merged={"other": 1})
        await self._run(service, cfg_path="brand.new", value="x")
        new_doc = service.set_local_config_context.call_args.args[1]
        self.assertEqual(new_doc, {"brand": {"new": "x"}})

    async def test_seeded_value_is_a_deep_copy_of_global(self) -> None:
        merged = {"tacacs": [{"key": "mykey", "address": "1.2.3.4"}]}
        service = _seeding_service(local={}, merged=merged)
        await self._run(service)
        self.assertEqual(merged["tacacs"][0]["key"], "mykey")

    async def test_append_with_a_path_is_seeded_too(self) -> None:
        service = _seeding_service(local={})
        await self._run(service, mode="append", cfg_path="tacacs", value=[{"address": "5.6.7.8"}])
        new_doc = service.set_local_config_context.call_args.args[1]
        self.assertEqual(new_doc["tacacs"], [{"address": "5.6.7.8"}])
        service.get_config_context.assert_awaited_once()

    async def test_write_and_empty_path_append_never_fetch_global(self) -> None:
        service = _seeding_service(local={})
        await self._run(service, mode="write", cfg_path="", value={"a": 1})
        await self._run(service, mode="append", cfg_path="", value={"b": 2})
        service.get_config_context.assert_not_awaited()


class RenderPathTests(unittest.TestCase):
    def test_substitutes_a_hyphenated_custom_attribute(self) -> None:
        device = _device("d1", custom={"tacacs-server": "tacacs-server"})
        self.assertEqual(
            _render_path("tacacs[server={custom.tacacs-server}].key", device),
            "tacacs[server=tacacs-server].key",
        )

    def test_substitutes_several_placeholders(self) -> None:
        device = _device("d1", custom={"srv": "a", "lvl": "7"})
        self.assertEqual(
            _render_path("tacacs[server={custom.srv}].levels[x={custom.lvl}]", device),
            "tacacs[server=a].levels[x=7]",
        )

    def test_value_with_dots_is_kept_whole(self) -> None:
        device = _device("d1", custom={"ip": "1.2.3.4"})
        self.assertEqual(
            _render_path("tacacs[address={custom.ip}].key", device),
            "tacacs[address=1.2.3.4].key",
        )

    def test_path_without_placeholders_is_unchanged(self) -> None:
        self.assertEqual(
            _render_path("tacacs[address=1.2.3.4].key", None), "tacacs[address=1.2.3.4].key"
        )

    def test_unresolved_placeholder_raises_naming_it(self) -> None:
        with self.assertRaisesRegex(ValueError, r"\{custom\.missing\}"):
            _render_path("tacacs[server={custom.missing}].key", _device("d1"))

    def test_placeholder_without_a_workflow_device_raises(self) -> None:
        with self.assertRaisesRegex(ValueError, "workflow device"):
            _render_path("tacacs[server={custom.srv}].key", None)

    def test_sealed_secret_value_fails_instead_of_substituting_the_redaction(self) -> None:
        device = _device("d1", custom={"srv": seal_secret("hunter2")})
        with self.assertRaisesRegex(ValueError, "secret"):
            _render_path("tacacs[server={custom.srv}].key", device)

    def test_dotted_value_outside_brackets_is_rejected(self) -> None:
        # servers.{x}.key with x="foo.bar" would silently walk an extra level.
        device = _device("d1", custom={"name": "foo.bar"})
        with self.assertRaisesRegex(ValueError, "dot"):
            _render_path("servers.{custom.name}.key", device)

    def test_plain_value_outside_brackets_is_substituted(self) -> None:
        device = _device("d1", custom={"name": "foo"})
        self.assertEqual(_render_path("servers.{custom.name}.key", device), "servers.foo.key")

    def test_value_containing_brackets_is_rejected(self) -> None:
        device = _device("d1", custom={"srv": "a]b"})
        with self.assertRaisesRegex(ValueError, "brackets"):
            _render_path("tacacs[server={custom.srv}].key", device)


class PathPlaceholderEndToEndTests(unittest.IsolatedAsyncioTestCase):
    async def _run(
        self, device: DeviceContext, local: dict
    ) -> tuple[bool, DeviceContext, MagicMock]:
        parsed = _parse_config(
            _attribute_config(
                "custom.new_key",
                mode="update",
                cfg_path="tacacs[server={custom.tacacs_server}].key",
            )
        )
        update_service = MagicMock()
        update_service.get_local_config_context = AsyncMock(return_value=local)
        update_service.set_local_config_context = AsyncMock()
        with patch.object(mod, "resolve_nautobot_device_id", AsyncMock(return_value="nb-1")):
            _, dev, ok = await _update_one_device(
                device_key="d1",
                device=device,
                parsed=parsed,
                context=WorkflowContext(run_id="r", workflow_id="w", devices={}),
                node_id="n",
                nautobot_service=MagicMock(),
                credentials=MagicMock(),
                update_service=update_service,
            )
        assert dev is not None
        return ok, dev, update_service

    async def test_updates_the_entry_selected_by_the_custom_attribute(self) -> None:
        device = _device("d1", custom={"tacacs_server": "backup", "new_key": "s3cret"})
        local = {
            "tacacs": [
                {"server": "primary", "key": "old1"},
                {"server": "backup", "key": "old2"},
            ]
        }
        ok, _, service = await self._run(device, local)
        self.assertTrue(ok)
        new_doc = service.set_local_config_context.call_args.args[1]
        self.assertEqual(new_doc["tacacs"][0]["key"], "old1")
        self.assertEqual(new_doc["tacacs"][1]["key"], "s3cret")

    async def test_unresolved_placeholder_fails_the_device_without_writing(self) -> None:
        device = _device("d1", custom={"new_key": "s3cret"})
        ok, dev, service = await self._run(device, {"tacacs": [{"server": "a", "key": "k"}]})
        self.assertFalse(ok)
        self.assertEqual(dev.status, DeviceStatus.FAILED)
        self.assertIn("custom.tacacs_server", dev.errors[-1].message)
        service.set_local_config_context.assert_not_awaited()


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
