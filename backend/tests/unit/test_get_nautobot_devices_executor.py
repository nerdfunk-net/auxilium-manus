"""get-nautobot-devices: how a step turns its configuration into devices.

A step with a selected saved inventory resolves that inventory *live* at run time
(the same code path as an inventory chosen from a run parameter), so editing the
saved inventory changes what the next run targets. Only a step without an
inventory id — an ad-hoc filter or device list — uses the copy in its own config.
"""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.sources_nautobot import DeviceInfo
from models.workflow_context import WorkflowContext
from workflow_steps.get_nautobot_devices import executor as mod

_TREE = {
    "id": "root",
    "logic": "OR",
    "negate": False,
    "items": [{"id": "1", "field": "name", "operator": "equals", "value": "OLD-SNAPSHOT"}],
}


def _dev(did: str) -> DeviceInfo:
    return DeviceInfo(id=did, name=did, primary_ip4="10.0.0.1/24")


def _config(**overrides) -> dict:
    cfg = {"nautobot_source_id": "src-1", "inventory_type": "filter"}
    cfg.update(overrides)
    return cfg


def _source_service(**returns) -> MagicMock:
    service = MagicMock()
    service.resolve_saved_inventory_devices_by_id = AsyncMock(
        return_value=returns.get("saved", [_dev("live-1"), _dev("live-2")])
    )
    service.preview_inventory = AsyncMock(return_value=(returns.get("filter", [_dev("snap")]), 1))
    service.resolve_devices_by_ids = AsyncMock(return_value=returns.get("static", [_dev("st")]))
    return service


async def _run(
    config: dict, service: MagicMock, *, run_inputs=None, username: str | None = "alice"
):
    run = MagicMock(id=5, triggered_by_id=7, run_inputs=run_inputs or {})
    with (
        patch.object(mod, "object_session", return_value=MagicMock()),
        patch.object(mod, "resolve_nautobot_credentials", return_value=MagicMock()),
        patch.object(mod, "_acting_username", return_value=username),
        patch.object(mod.service_factory, "build_nautobot_source_service", return_value=service),
    ):
        outcomes = await mod.execute(
            config=config,
            context=WorkflowContext(run_id="r", workflow_id="w"),
            run=run,
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )
    return outcomes[0].context


class SelectedInventoryIsResolvedLiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_inventory_id_resolves_the_saved_inventory_not_the_copy(self) -> None:
        service = _source_service()
        config = _config(inventory_id=42, inventory_name="LAB", device_filter=_TREE)

        context = await _run(config, service)

        service.resolve_saved_inventory_devices_by_id.assert_awaited_once_with(42, "alice")
        service.preview_inventory.assert_not_awaited()
        service.resolve_devices_by_ids.assert_not_awaited()
        self.assertEqual(sorted(context.devices), ["live-1", "live-2"])
        self.assertEqual(context.metadata["n1.total"], 2)

    async def test_the_saved_inventory_wins_over_a_stale_static_device_list(self) -> None:
        service = _source_service()
        config = _config(inventory_id=42, inventory_type="static", device_ids=["old-a", "old-b"])

        context = await _run(config, service)

        service.resolve_saved_inventory_devices_by_id.assert_awaited_once()
        service.resolve_devices_by_ids.assert_not_awaited()
        self.assertEqual(sorted(context.devices), ["live-1", "live-2"])

    async def test_two_runs_see_an_edited_inventory(self) -> None:
        service = _source_service()
        config = _config(inventory_id=42, device_filter=_TREE)

        first = await _run(config, service)
        service.resolve_saved_inventory_devices_by_id.return_value = [_dev("edited")]
        second = await _run(config, service)

        self.assertEqual(sorted(first.devices), ["live-1", "live-2"])
        self.assertEqual(sorted(second.devices), ["edited"])

    async def test_run_parameter_and_fixed_id_use_the_same_call(self) -> None:
        fixed_service, param_service = _source_service(), _source_service()

        await _run(_config(inventory_id=42), fixed_service)
        await _run(
            _config(inventory_source="run_param", inventory_param="target"),
            param_service,
            run_inputs={"target": "42"},
        )

        for service in (fixed_service, param_service):
            service.resolve_saved_inventory_devices_by_id.assert_awaited_once_with(42, "alice")

    async def test_a_run_parameter_takes_precedence_over_the_fixed_id(self) -> None:
        service = _source_service()
        config = _config(inventory_id=1, inventory_source="run_param", inventory_param="target")

        await _run(config, service, run_inputs={"target": "9"})

        service.resolve_saved_inventory_devices_by_id.assert_awaited_once_with(9, "alice")

    async def test_the_acting_user_scopes_access_and_system_runs_have_none(self) -> None:
        service = _source_service()

        await _run(_config(inventory_id=42), service, username=None)

        service.resolve_saved_inventory_devices_by_id.assert_awaited_once_with(42, None)


class AdHocSnapshotStillWorksTests(unittest.IsolatedAsyncioTestCase):
    async def test_filter_without_an_inventory_id_uses_its_own_filter(self) -> None:
        service = _source_service()

        context = await _run(_config(device_filter=_TREE), service)

        service.resolve_saved_inventory_devices_by_id.assert_not_awaited()
        service.preview_inventory.assert_awaited_once()
        operations = service.preview_inventory.await_args.args[0]
        self.assertEqual(operations[0].conditions[0].value, "OLD-SNAPSHOT")
        self.assertEqual(list(context.devices), ["snap"])

    async def test_static_list_without_an_inventory_id_uses_its_own_ids(self) -> None:
        service = _source_service()

        context = await _run(_config(inventory_type="static", device_ids=["st"]), service)

        service.resolve_devices_by_ids.assert_awaited_once_with(["st"])
        service.resolve_saved_inventory_devices_by_id.assert_not_awaited()
        self.assertEqual(list(context.devices), ["st"])

    async def test_empty_or_zero_inventory_id_counts_as_no_inventory(self) -> None:
        for empty in (None, 0, ""):
            with self.subTest(inventory_id=empty):
                service = _source_service()
                await _run(_config(inventory_id=empty, device_filter=_TREE), service)
                service.resolve_saved_inventory_devices_by_id.assert_not_awaited()
                service.preview_inventory.assert_awaited_once()


class ErrorTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_deleted_inventory_fails_the_step_and_names_it(self) -> None:
        service = _source_service()
        service.resolve_saved_inventory_devices_by_id.side_effect = ValueError(
            "Inventory with ID 2 not found"
        )
        config = _config(inventory_id=2, inventory_name="Full lab env", device_filter=_TREE)

        with self.assertRaises(ValueError) as ctx:
            await _run(config, service)

        message = str(ctx.exception)
        self.assertIn("get-nautobot-devices", message)
        self.assertIn("2", message)
        self.assertIn("Full lab env", message)
        self.assertIn("not found", message)
        service.preview_inventory.assert_not_awaited()  # never silently falls back to the copy

    async def test_a_private_inventory_of_someone_else_is_reported_as_inaccessible(self) -> None:
        service = _source_service()
        service.resolve_saved_inventory_devices_by_id.side_effect = PermissionError("private")

        with self.assertRaises(ValueError) as ctx:
            await _run(_config(inventory_id=3), service)

        self.assertIn("not accessible", str(ctx.exception))

    async def test_a_non_numeric_inventory_reference_is_a_configuration_error(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            await _run(_config(inventory_id="abc"), _source_service())

        self.assertIn("inventory id", str(ctx.exception))

    async def test_run_parameter_missing_from_the_run_inputs_still_fails(self) -> None:
        config = _config(inventory_source="run_param", inventory_param="target")

        with self.assertRaises(ValueError):
            await _run(config, _source_service(), run_inputs={})

    async def test_source_id_is_still_required(self) -> None:
        with self.assertRaises(ValueError):
            await _run({"inventory_id": 1}, _source_service())


if __name__ == "__main__":
    unittest.main()
