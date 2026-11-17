"""Executor of get-catalyst-center-client-data (mocked service and storage, no network)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from models.catalyst_center_facts import CatalystCenterClient
from models.client_data import CollectionConflictError, TooManyRowsError
from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.catalyst_center.common.exceptions import CatalystCenterAuthError
from services.catalyst_center.source_config_service import CatalystCenterSourceNotFoundError
from workflow_steps.get_catalyst_center_client_data.executor import execute

MODULE = "workflow_steps.get_catalyst_center_client_data.executor"


def _device(device_id: str, *, name: str | None = None, source: str = "catalyst_center"):
    """Built like ``device_context_from_catalyst_center``: ``hostname`` is the management IP."""
    return DeviceContext(
        id=device_id,
        name=name or device_id,
        hostname="10.1.1.1",
        primary_ip4="10.1.1.1",
        platform="IOS-XE",
        source=source,
        source_id="lab",
    )


def _context(*devices: DeviceContext) -> WorkflowContext:
    return WorkflowContext(run_id="run-1", workflow_id="wf-1", devices={d.id: d for d in devices})


def _client(mac: str = "aa:bb:cc:dd:ee:01", device_id: str | None = "a") -> CatalystCenterClient:
    return CatalystCenterClient(
        mac_address=mac,
        ip_addresses=("10.0.0.5",),
        vlan="10",
        port="GigabitEthernet1/0/3",
        connected_device_id=device_id,
    )


class _Env:
    """Patches the DB session, credential resolution, the service builder and the storage."""

    def __init__(self, clients=(), *, service_error=None, store_error=None, resolve_error=None):
        self.service = MagicMock()
        if service_error is not None:
            self.service.get_wired_clients = AsyncMock(side_effect=service_error)
        else:
            self.service.get_wired_clients = AsyncMock(return_value=tuple(clients))
        self.source_config = MagicMock()
        if resolve_error is not None:
            self.source_config.resolve_credentials.side_effect = resolve_error
        self.store = MagicMock(side_effect=store_error)

    def __enter__(self):
        self._patches = [
            patch(f"{MODULE}.object_session", return_value=MagicMock()),
            patch(
                "service_factory.build_catalyst_center_source_config_service",
                return_value=self.source_config,
            ),
            patch(
                "service_factory.build_catalyst_center_client_data_service",
                return_value=self.service,
            ),
            patch(f"{MODULE}._store_sync", self.store),
        ]
        for p in self._patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self._patches:
            p.stop()


async def _run(config: dict, context: WorkflowContext):
    run = MagicMock()
    run.id = 1
    run.uuid = "run-uuid"
    return await execute(
        config=config,
        context=context,
        run=run,
        artifact_service=InMemoryArtifactService(),
        node_id="node-1",
        device_sessions=MagicMock(),
    )


def _by_name(outcomes):
    return {o.name: o for o in outcomes}


class ConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_lookback_raises_before_any_io(self) -> None:
        for value in (0, 169, "x", True, 1.5):
            with self.subTest(value=value), _Env() as env:
                with self.assertRaisesRegex(ValueError, "lookback_hours"):
                    await _run({"lookback_hours": value}, _context(_device("a")))
                env.source_config.resolve_credentials.assert_not_called()

    async def test_unknown_source_is_a_value_error(self) -> None:
        with _Env(resolve_error=CatalystCenterSourceNotFoundError("lab")):
            with self.assertRaisesRegex(ValueError, "'lab' not found"):
                await _run({}, _context(_device("a")))

    async def test_no_devices_is_a_noop_success(self) -> None:
        with _Env() as env:
            outcomes = await _run({}, _context())
        self.assertEqual([o.name for o in outcomes], ["success"])
        env.service.get_wired_clients.assert_not_called()


class CollectTests(unittest.IsolatedAsyncioTestCase):
    async def test_stores_rows_and_summarises(self) -> None:
        with _Env([_client()]) as env:
            outcomes = _by_name(
                await _run({"lookback_hours": 48}, _context(_device("a", name="sw1")))
            )
        self.assertEqual(list(outcomes), ["success"])
        # The controller is asked about the device UUID, not the name or the management IP.
        env.service.get_wired_clients.assert_awaited_once_with("a", lookback_hours=48)
        kwargs = env.store.call_args.kwargs
        self.assertEqual(kwargs["session_id"], "run-uuid")
        self.assertEqual(len(kwargs["ip_rows"]), 1)
        self.assertEqual(len(kwargs["mac_rows"]), 1)
        self.assertEqual(kwargs["mac_rows"][0].port, "Gi1/0/3")
        self.assertEqual(kwargs["target_host"], "catalyst_center:lab:a")
        device = outcomes["success"].context.devices["a"]
        self.assertEqual(device.status, DeviceStatus.OK)
        self.assertIn(Capability.PARSED, device.capabilities)
        summary = device.parsed["node-1"]["client_data"]
        self.assertEqual((summary["arp_entries"], summary["mac_entries"]), (1, 1))
        self.assertEqual(summary["lookback_hours"], 48)

    async def test_no_clients_is_a_success_that_is_still_stored(self) -> None:
        with _Env([]) as env:
            outcomes = _by_name(await _run({}, _context(_device("a"))))
        self.assertEqual(list(outcomes), ["success"])
        self.assertEqual(env.store.call_args.kwargs["ip_rows"], ())
        self.assertEqual(env.store.call_args.kwargs["mac_rows"], ())

    async def test_client_of_another_switch_is_dropped(self) -> None:
        with _Env([_client(device_id="other"), _client("aa:bb:cc:dd:ee:02", device_id="a")]) as env:
            await _run({}, _context(_device("a")))
        self.assertEqual(len(env.store.call_args.kwargs["mac_rows"]), 1)

    async def test_clients_none_of_which_is_usable_fail_and_store_nothing(self) -> None:
        for clients in (
            [_client(device_id="other")],
            [_client(device_id=None)],
            [_client(mac="garbage")],
        ):
            with self.subTest(clients=clients), _Env(clients) as env:
                outcomes = _by_name(await _run({}, _context(_device("a"))))
            err = outcomes["failure"].context.devices["a"].errors[-1]
            self.assertEqual(err.code, "no_usable_clients")
            self.assertEqual(outcomes["success"].context.devices, {})
            env.store.assert_not_called()

    async def test_non_catalyst_device_is_rejected(self) -> None:
        with _Env([_client()]) as env:
            outcomes = _by_name(
                await _run({}, _context(_device("a"), _device("b", source="nautobot")))
            )
        self.assertEqual(list(outcomes["success"].context.devices), ["a"])
        failed = outcomes["failure"].context.devices["b"]
        self.assertEqual(failed.errors[-1].code, "not_catalyst_center_device")
        self.assertEqual(env.service.get_wired_clients.await_count, 1)

    async def test_duplicate_names_fail_the_second_device(self) -> None:
        with _Env([_client()]) as env:
            outcomes = _by_name(
                await _run({}, _context(_device("a", name="sw1"), _device("b", name="sw1")))
            )
        self.assertEqual(list(outcomes["success"].context.devices), ["a"])
        self.assertEqual(outcomes["failure"].context.devices["b"].errors[-1].code, "duplicate_key")
        self.assertEqual(env.store.call_count, 1)

    async def test_dry_run_neither_queries_nor_stores(self) -> None:
        with _Env([_client()]) as env:
            outcomes = _by_name(await _run({"dry_run": True}, _context(_device("a"))))
        device = outcomes["success"].context.devices["a"]
        self.assertIn("node-1", device.dry_run_results)
        env.service.get_wired_clients.assert_not_called()
        env.store.assert_not_called()


class FailureTests(unittest.IsolatedAsyncioTestCase):
    async def test_controller_error_fails_only_that_device(self) -> None:
        error = CatalystCenterAuthError("denied", http_status=403, code="request_denied")
        with _Env(service_error=error) as env:
            outcomes = _by_name(await _run({}, _context(_device("a"))))
        self.assertEqual(outcomes["success"].context.devices, {})
        err = outcomes["failure"].context.devices["a"].errors[-1]
        self.assertEqual(err.code, "catalyst_center_error")
        self.assertIsNotNone(err.failure)
        env.store.assert_not_called()

    async def test_storage_conflict_is_a_duplicate_key(self) -> None:
        with _Env([_client()], store_error=CollectionConflictError()):
            outcomes = _by_name(await _run({}, _context(_device("a"))))
        self.assertEqual(outcomes["failure"].context.devices["a"].errors[-1].code, "duplicate_key")

    async def test_row_cap_fails_the_device(self) -> None:
        with _Env([_client()], store_error=TooManyRowsError("MAC", 5)):
            outcomes = _by_name(await _run({}, _context(_device("a"))))
        self.assertEqual(outcomes["failure"].context.devices["a"].errors[-1].code, "too_many_rows")

    async def test_storage_error_keeps_only_the_class_name(self) -> None:
        with _Env([_client()], store_error=ValueError("secret SQL text")):
            outcomes = _by_name(await _run({}, _context(_device("a"))))
        err = outcomes["failure"].context.devices["a"].errors[-1]
        self.assertEqual(err.code, "storage_failed")
        self.assertNotIn("secret", err.message)
