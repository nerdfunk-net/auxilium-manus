"""Tests for store-for-report executor."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.base import Base
from core.models.report_data_records import ReportDataRecord
from models.workflow_context import DeviceContext, WorkflowContext
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.store_for_report.config import get_config
from workflow_steps.store_for_report.executor import execute

FIELDS = [
    {"name": "serial_number", "attribute_path": "nautobot.serial"},
    {"name": "device_type", "attribute_path": "nautobot.device_type.model"},
]


def _device(device_id: str = "d1", name: str = "lab", **overrides: object) -> DeviceContext:
    defaults: dict[str, object] = {
        "id": device_id,
        "name": name,
        "hostname": name,
        "attribute_bags": {
            "nautobot": {"serial": "FOC123", "device_type": {"model": "C9300"}, "ports": 48}
        },
    }
    defaults.update(overrides)
    return DeviceContext(**defaults)


class _ExecutorTestBase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(self.engine, tables=[ReportDataRecord.__table__])
        self.addCleanup(self.engine.dispose)
        self.Session = sessionmaker(bind=self.engine)
        patcher = patch(
            "workflow_steps.store_for_report.executor.get_db_session",
            side_effect=lambda: self.Session(),
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _rows(self) -> list[ReportDataRecord]:
        with self.Session() as db:
            return list(db.scalars(select(ReportDataRecord).order_by(ReportDataRecord.id)))

    async def _run(
        self,
        *,
        config: dict,
        devices: list[DeviceContext],
        run_id: int = 5,
        node_id: str = "store-for-report-1",
    ):
        run = MagicMock()
        run.id = run_id
        return await execute(
            config=config,
            context=WorkflowContext(
                run_id="run-1", workflow_id="wf-1", devices={d.id: d for d in devices}
            ),
            run=run,
            artifact_service=MagicMock(),
            node_id=node_id,
            device_sessions=MagicMock(),
        )


class StoreForReportExecutorTests(_ExecutorTestBase):
    async def test_stores_mapped_fields_with_run_id(self) -> None:
        outcomes = await self._run(
            config={"dataset": "inventory", "fields": FIELDS}, devices=[_device()]
        )

        self.assertEqual([o.name for o in outcomes], ["success"])
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].device_name, "lab")
        self.assertEqual(rows[0].dataset, "inventory")
        self.assertEqual(rows[0].run_id, 5)
        self.assertEqual(rows[0].data, {"serial_number": "FOC123", "device_type": "C9300"})

    async def test_a_second_node_writing_the_same_dataset_fails_the_device_loudly(self) -> None:
        config = {"dataset": "inventory", "fields": FIELDS}
        await self._run(config=config, devices=[_device()])

        outcomes = await self._run(config=config, devices=[_device()], node_id="store-for-report-2")

        failure = next(o for o in outcomes if o.name == "failure")
        self.assertEqual(list(failure.context.devices), ["d1"])
        self.assertIn("store-for-report-1", failure.context.devices["d1"].errors[0].message)
        self.assertEqual(len(self._rows()), 1)

    async def test_the_same_node_running_again_replaces_its_rows(self) -> None:
        config = {"dataset": "inventory", "fields": FIELDS}
        await self._run(config=config, devices=[_device()])
        outcomes = await self._run(config=config, devices=[_device()])

        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertEqual(len(self._rows()), 1)
        self.assertEqual(self._rows()[0].node_id, "store-for-report-1")

    async def test_missing_path_stores_null(self) -> None:
        fields = [*FIELDS, {"name": "rack", "attribute_path": "nautobot.rack.name"}]
        outcomes = await self._run(
            config={"dataset": "inventory", "fields": fields}, devices=[_device()]
        )

        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertIsNone(self._rows()[0].data["rack"])

    # --- a field that is empty for every device is reported (O4-05) ----------------

    async def test_field_empty_for_every_device_is_named_in_the_summary(self) -> None:
        fields = [*FIELDS, {"name": "ip", "attribute_path": "ip_address"}]
        with self.assertLogs("workflow_steps.store_for_report.executor", "WARNING") as logs:
            outcomes = await self._run(
                config={"dataset": "inventory", "fields": fields},
                devices=[_device("d1", "a"), _device("d2", "b")],
            )

        success = outcomes[0]
        self.assertEqual(success.name, "success")  # the step still succeeds
        self.assertIn("'ip'", success.summary or "")
        self.assertIn("2 device(s)", success.summary or "")
        self.assertNotIn("serial_number", success.summary or "")
        self.assertTrue(any("ip" in line for line in logs.output))
        self.assertEqual(len(self._rows()), 2)

    async def test_field_with_a_value_on_some_devices_is_not_reported(self) -> None:
        fields = [*FIELDS, {"name": "rack", "attribute_path": "nautobot.rack"}]
        with_rack = _device("d1", "a", attribute_bags={"nautobot": {"rack": "R1"}})
        outcomes = await self._run(
            config={"dataset": "inventory", "fields": fields},
            devices=[with_rack, _device("d2", "b")],
        )

        self.assertIsNone(outcomes[0].summary)  # rack is set on one device; serial on the other

    async def test_all_fields_filled_has_no_summary(self) -> None:
        outcomes = await self._run(
            config={"dataset": "inventory", "fields": FIELDS}, devices=[_device()]
        )

        self.assertIsNone(outcomes[0].summary)

    async def test_count_of_missing_list_for_every_device_is_reported(self) -> None:
        fields = [{"name": "n", "attribute_path": "nautobot.interfaces", "aggregate": "count"}]
        outcomes = await self._run(
            config={"dataset": "inventory", "fields": fields}, devices=[_device()]
        )

        self.assertIn("'n'", outcomes[0].summary or "")

    async def test_numbers_are_stored_as_numbers(self) -> None:
        fields = [{"name": "ports", "attribute_path": "nautobot.ports"}]
        await self._run(config={"dataset": "inventory", "fields": fields}, devices=[_device()])
        self.assertEqual(self._rows()[0].data, {"ports": 48})

    async def test_non_scalar_value_fails_only_that_device(self) -> None:
        bad = _device("d2", "bad", attribute_bags={"nautobot": {"serial": ["a", "b"]}})
        fields = [{"name": "serial_number", "attribute_path": "nautobot.serial"}]
        outcomes = await self._run(
            config={"dataset": "inventory", "fields": fields}, devices=[_device(), bad]
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(set(by_name), {"success", "failure"})
        self.assertEqual(list(by_name["success"].context.devices), ["d1"])
        self.assertEqual(list(by_name["failure"].context.devices), ["d2"])
        self.assertEqual([r.device_name for r in self._rows()], ["lab"])

    async def test_sealed_secret_fails_device(self) -> None:
        secret = _device(attribute_bags={"nautobot": {"serial": seal_secret("s3cr3t")}})
        fields = [{"name": "serial_number", "attribute_path": "nautobot.serial"}]
        outcomes = await self._run(
            config={"dataset": "inventory", "fields": fields}, devices=[secret]
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(by_name["success"].context.devices, {})
        failed = by_name["failure"].context.devices["d1"]
        self.assertIn("secret", failed.errors[0].message.lower())
        self.assertEqual(self._rows(), [])

    async def test_rerun_in_same_run_updates_row(self) -> None:
        config = {"dataset": "inventory", "fields": FIELDS}
        await self._run(config=config, devices=[_device()])
        await self._run(config=config, devices=[_device()])
        self.assertEqual(len(self._rows()), 1)

    async def test_new_run_appends_history(self) -> None:
        config = {"dataset": "inventory", "fields": FIELDS}
        await self._run(config=config, devices=[_device()], run_id=1)
        await self._run(config=config, devices=[_device()], run_id=2)
        self.assertEqual([r.run_id for r in self._rows()], [1, 2])

    async def test_duplicate_device_name_in_run_fails_later_device(self) -> None:
        first = _device("d1", "lab")
        second = _device("d2", "lab")
        outcomes = await self._run(
            config={"dataset": "inventory", "fields": FIELDS}, devices=[first, second]
        )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["success"].context.devices), ["d1"])
        self.assertEqual(list(by_name["failure"].context.devices), ["d2"])
        self.assertIn("duplicate", by_name["failure"].context.devices["d2"].errors[0].message)
        self.assertEqual(len(self._rows()), 1)

    async def test_run_id_path_resolves_to_the_run_uuid(self) -> None:
        fields = [{"name": "run", "attribute_path": "run.id"}]
        await self._run(
            config={"dataset": "inventory", "fields": fields}, devices=[_device()], run_id=42
        )
        # The workflow context carries the run UUID ("run-1" in these tests), like every
        # other step; the integer primary key only goes into the run_id column.
        self.assertEqual(self._rows()[0].data["run"], "run-1")
        self.assertEqual(self._rows()[0].run_id, 42)

    async def test_db_error_on_one_device_does_not_fail_the_rest(self) -> None:
        from sqlalchemy.exc import DataError

        from services.report_data.report_data_service import ReportDataService

        real = ReportDataService.record_device_data

        def flaky(self, **kwargs):  # type: ignore[no-untyped-def]
            if kwargs["device_name"] == "bad":
                raise DataError("INSERT secret-value", {"p": "secret-value"}, Exception("boom"))
            return real(self, **kwargs)

        with patch.object(ReportDataService, "record_device_data", flaky):
            outcomes = await self._run(
                config={"dataset": "inventory", "fields": FIELDS},
                devices=[_device("d1", "bad"), _device("d2", "good")],
            )

        by_name = {o.name: o for o in outcomes}
        self.assertEqual(list(by_name["success"].context.devices), ["d2"])
        failed = by_name["failure"].context.devices["d1"]
        self.assertNotIn("secret-value", failed.errors[0].message)

    async def test_secret_shaped_path_or_name_is_a_config_error(self) -> None:
        bad_fields = [
            {"name": "community", "attribute_path": "nautobot.serial"},
            {"name": "x", "attribute_path": "nautobot.snmp.community"},
            {"name": "x", "attribute_path": "parsed.users[name=a].password"},
            {"name": "x", "attribute_path": "tacacs.shared_secret"},
            {"name": "x", "attribute_path": "nautobot.api_token"},
        ]
        for field in bad_fields:
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "secret"):
                await self._run(
                    config={"dataset": "inventory", "fields": [field]}, devices=[_device()]
                )

    async def test_run_registered_cleartext_secret_fails_device(self) -> None:
        from services.workflow_context.secret_fields import (
            register_secret_value,
            run_secret_scope,
        )

        device = _device(attribute_bags={"nautobot": {"serial": "hunter2-hunter2"}})
        fields = [{"name": "serial_number", "attribute_path": "nautobot.serial"}]
        with run_secret_scope():
            register_secret_value("hunter2-hunter2")
            outcomes = await self._run(
                config={"dataset": "inventory", "fields": fields}, devices=[device]
            )

        by_name = {o.name: o for o in outcomes}
        self.assertIn("d1", by_name["failure"].context.devices)
        self.assertEqual(self._rows(), [])

    async def test_count_fields_skip_the_secret_name_check(self) -> None:
        fields = [
            {
                "name": "user_count",
                "attribute_path": "parsed.users.password_list",
                "aggregate": "count",
            }
        ]
        device = _device(parsed={"users": {"password_list": [1, 2]}})
        await self._run(config={"dataset": "inventory", "fields": fields}, devices=[device])
        self.assertEqual(self._rows()[0].data, {"user_count": 2})

    async def test_unexpected_error_is_logged_with_traceback(self) -> None:
        from services.report_data.report_data_service import ReportDataService

        def broken(self, **kwargs):  # type: ignore[no-untyped-def]
            raise TypeError("'collection_id' is an invalid keyword argument")

        with (
            patch.object(ReportDataService, "record_device_data", broken),
            self.assertLogs("workflow_steps.store_for_report.executor", level="ERROR") as logs,
        ):
            outcomes = await self._run(
                config={"dataset": "inventory", "fields": FIELDS}, devices=[_device()]
            )

        self.assertIn("failure", [o.name for o in outcomes])
        self.assertIn("collection_id", "\n".join(logs.output))
        self.assertIn("Traceback", "\n".join(logs.output))
        # the run result must not carry the exception text (it can hold paths and values)
        error = next(o for o in outcomes if o.name == "failure").context.devices["d1"].errors[0]
        self.assertNotIn("collection_id", error.message)
        self.assertEqual(error.message, "unexpected error while storing report data")
        self.assertEqual(error.failure.phase, "internal")  # type: ignore[union-attr]
        self.assertEqual(error.failure.kind, "internal_error")  # type: ignore[union-attr]
        self.assertEqual(error.failure.exception_type, "TypeError")  # type: ignore[union-attr]

    async def test_failures_carry_a_structured_record(self) -> None:
        from sqlalchemy.exc import DataError

        from services.report_data.report_data_service import ReportDataService

        bad_value = _device("d2", "bad", attribute_bags={"nautobot": {"serial": ["a", "b"]}})
        fields = [{"name": "serial_number", "attribute_path": "nautobot.serial"}]
        outcomes = await self._run(
            config={"dataset": "inventory", "fields": fields},
            devices=[_device("d1", "lab"), _device("d3", "lab"), bad_value],
        )
        failed = {
            d.name: d.errors[0]
            for o in outcomes
            if o.name == "failure"
            for d in o.context.devices.values()
        }

        # an unusable value and a duplicate name are input problems, not bugs
        for name in ("bad",):
            self.assertEqual(
                (failed[name].failure.phase, failed[name].failure.kind), ("config", "bad_request")
            )  # type: ignore[union-attr]
        self.assertEqual(failed["lab"].code, "duplicate_device_name")
        self.assertEqual(failed["lab"].failure.kind, "bad_request")  # type: ignore[union-attr]

        def db_fail(self, **kwargs):  # type: ignore[no-untyped-def]
            raise DataError("INSERT secret-value", {"p": "secret-value"}, Exception("boom"))

        with patch.object(ReportDataService, "record_device_data", db_fail):
            outcomes = await self._run(
                config={"dataset": "inventory", "fields": FIELDS}, devices=[_device()]
            )
        error = next(o for o in outcomes if o.name == "failure").context.devices["d1"].errors[0]
        self.assertEqual((error.failure.phase, error.failure.kind), ("internal", "internal_error"))  # type: ignore[union-attr]
        self.assertEqual(error.failure.exception_type, "DataError")  # type: ignore[union-attr]

    async def test_expected_device_failure_is_logged_as_a_warning(self) -> None:
        bad = _device("d2", "bad", attribute_bags={"nautobot": {"serial": ["a", "b"]}})
        fields = [{"name": "serial_number", "attribute_path": "nautobot.serial"}]
        with self.assertLogs("workflow_steps.store_for_report.executor", level="WARNING") as logs:
            await self._run(config={"dataset": "inventory", "fields": fields}, devices=[bad])

        self.assertIn("bad", "\n".join(logs.output))
        self.assertNotIn("Traceback", "\n".join(logs.output))

    async def test_no_devices_is_a_noop_success(self) -> None:
        outcomes = await self._run(config={"dataset": "inventory", "fields": FIELDS}, devices=[])
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertEqual(self._rows(), [])

    async def test_invalid_config_raises_value_error(self) -> None:
        bad_configs = [
            {"dataset": "", "fields": FIELDS},
            {"dataset": "Bad Name", "fields": FIELDS},
            {"dataset": "inventory", "fields": []},
            {"dataset": "inventory", "fields": "nope"},
            {"dataset": "inventory", "fields": [{"name": "Bad", "attribute_path": "a.b"}]},
            {"dataset": "inventory", "fields": [{"name": "ok", "attribute_path": ""}]},
            {
                "dataset": "inventory",
                "fields": [
                    {"name": "dup", "attribute_path": "a.b"},
                    {"name": "dup", "attribute_path": "a.c"},
                ],
            },
        ]
        for config in bad_configs:
            with self.subTest(config=config), self.assertRaises(ValueError):
                await self._run(config=config, devices=[_device()])

    def test_default_config_shape(self) -> None:
        self.assertEqual(
            get_config(), {"dataset": "", "mode": "device", "items_path": "", "fields": []}
        )


IFACES = [
    {"intf": "Gi1", "status": "connected", "vlan": 10},
    {"intf": "Gi2", "status": "disabled", "vlan": 20},
    {"intf": "Gi3", "status": "disabled", "vlan": 20},
]
IFACE_PATH = "parsed.parsed.show interfaces status.parsed"


def _iface_device(device_id: str = "d1", name: str = "lab", ifaces: object = IFACES):
    parsed = {"parsed": {"show interfaces status": {"parsed": ifaces, "error": None}}}
    return _device(device_id, name, parsed=parsed)


class StoreForReportCountTests(_ExecutorTestBase):
    def _count_config(self, **field: object) -> dict:
        return {
            "dataset": "inventory",
            "fields": [{"name": "n", "attribute_path": IFACE_PATH, "aggregate": "count", **field}],
        }

    async def test_count_counts_list_items(self) -> None:
        await self._run(config=self._count_config(), devices=[_iface_device()])
        self.assertEqual(self._rows()[0].data, {"n": 3})

    async def test_count_with_where_counts_matching_items(self) -> None:
        config = self._count_config(where_field="status", where_equals="disabled")
        await self._run(config=config, devices=[_iface_device()])
        self.assertEqual(self._rows()[0].data, {"n": 2})

    async def test_where_compares_numbers_and_booleans_as_text(self) -> None:
        ifaces = [{"vlan": 10, "up": True}, {"vlan": 20, "up": False}]
        fields = [
            {
                "name": "v10",
                "attribute_path": IFACE_PATH,
                "aggregate": "count",
                "where_field": "vlan",
                "where_equals": "10",
            },
            {
                "name": "down",
                "attribute_path": IFACE_PATH,
                "aggregate": "count",
                "where_field": "up",
                "where_equals": "false",
            },
        ]
        await self._run(
            config={"dataset": "inventory", "fields": fields},
            devices=[_iface_device(ifaces=ifaces)],
        )
        self.assertEqual(self._rows()[0].data, {"v10": 1, "down": 1})

    async def test_count_of_empty_list_is_zero(self) -> None:
        await self._run(config=self._count_config(), devices=[_iface_device(ifaces=[])])
        self.assertEqual(self._rows()[0].data, {"n": 0})

    async def test_count_of_missing_path_is_null_not_zero(self) -> None:
        await self._run(config=self._count_config(), devices=[_device()])
        self.assertEqual(self._rows()[0].data, {"n": None})

    async def test_count_of_non_list_fails_device(self) -> None:
        outcomes = await self._run(config=self._count_config(), devices=[_iface_device(ifaces="x")])
        self.assertEqual([o.name for o in outcomes if o.context.devices], ["failure"])
        self.assertEqual(self._rows(), [])

    async def test_count_ignores_secrets_elsewhere_in_the_list(self) -> None:
        users = [{"name": "a", "password": seal_secret("x")}, {"name": "b"}]
        await self._run(config=self._count_config(), devices=[_iface_device(ifaces=users)])
        self.assertEqual(self._rows()[0].data, {"n": 2})

    async def test_invalid_aggregate_config_raises(self) -> None:
        bad = [
            self._count_config(aggregate="sum"),
            self._count_config(aggregate="", where_field="status", where_equals="x"),
            self._count_config(where_field="status"),
        ]
        for config in bad:
            with self.subTest(config=config), self.assertRaises(ValueError):
                await self._run(config=config, devices=[_iface_device()])


class StoreForReportItemsTests(_ExecutorTestBase):
    CONFIG = {
        "dataset": "interfaces",
        "mode": "items",
        "items_path": IFACE_PATH,
        "fields": [
            {"name": "name", "attribute_path": "intf"},
            {"name": "status", "attribute_path": "status"},
        ],
    }

    async def test_stores_one_row_per_item(self) -> None:
        outcomes = await self._run(config=self.CONFIG, devices=[_iface_device()])

        self.assertEqual([o.name for o in outcomes], ["success"])
        rows = self._rows()
        self.assertEqual(
            [row.data for row in rows],
            [
                {"name": "Gi1", "status": "connected"},
                {"name": "Gi2", "status": "disabled"},
                {"name": "Gi3", "status": "disabled"},
            ],
        )
        self.assertEqual({row.device_name for row in rows}, {"lab"})
        self.assertEqual({row.run_id for row in rows}, {5})
        self.assertEqual(len({row.collection_id for row in rows}), 1)

    async def test_missing_item_field_is_null(self) -> None:
        config = {**self.CONFIG, "fields": [{"name": "speed", "attribute_path": "speed"}]}
        await self._run(config=config, devices=[_iface_device()])
        self.assertEqual({tuple(row.data.items()) for row in self._rows()}, {(("speed", None),)})

    async def test_scalar_items_use_dot_path(self) -> None:
        device = _device(parsed={"ntp": ["10.0.0.1", "10.0.0.2"]})
        config = {
            "dataset": "ntp_servers",
            "mode": "items",
            "items_path": "parsed.ntp",
            "fields": [{"name": "address", "attribute_path": "."}],
        }
        await self._run(config=config, devices=[device])
        self.assertEqual(
            [row.data for row in self._rows()], [{"address": "10.0.0.1"}, {"address": "10.0.0.2"}]
        )

    async def test_empty_list_stores_a_marker(self) -> None:
        outcomes = await self._run(config=self.CONFIG, devices=[_iface_device(ifaces=[])])

        self.assertEqual([o.name for o in outcomes], ["success"])
        (row,) = self._rows()
        self.assertTrue(row.is_empty)

    async def test_missing_list_fails_device(self) -> None:
        outcomes = await self._run(config=self.CONFIG, devices=[_device()])

        by_name = {o.name: o for o in outcomes}
        self.assertIn("d1", by_name["failure"].context.devices)
        self.assertEqual(self._rows(), [])

    async def test_non_list_fails_device(self) -> None:
        outcomes = await self._run(config=self.CONFIG, devices=[_iface_device(ifaces={"a": 1})])
        self.assertIn("failure", [o.name for o in outcomes])
        self.assertEqual(self._rows(), [])

    async def test_secret_item_field_fails_device(self) -> None:
        users = [{"intf": "a", "status": seal_secret("x")}]
        outcomes = await self._run(config=self.CONFIG, devices=[_iface_device(ifaces=users)])
        self.assertIn("failure", [o.name for o in outcomes])
        self.assertEqual(self._rows(), [])

    async def test_secret_shaped_item_path_is_a_config_error(self) -> None:
        config = {
            **self.CONFIG,
            "fields": [{"name": "pw", "attribute_path": "credentials.password"}],
        }
        with self.assertRaisesRegex(ValueError, "secret"):
            await self._run(config=config, devices=[_iface_device()])

    async def test_rerun_in_same_run_replaces_the_items(self) -> None:
        await self._run(config=self.CONFIG, devices=[_iface_device()])
        await self._run(config=self.CONFIG, devices=[_iface_device(ifaces=IFACES[:1])])
        self.assertEqual(len(self._rows()), 1)

    async def test_invalid_items_config_raises(self) -> None:
        bad = [
            {**self.CONFIG, "items_path": ""},
            {**self.CONFIG, "mode": "bogus"},
            {
                **self.CONFIG,
                "fields": [{"name": "n", "attribute_path": "intf", "aggregate": "count"}],
            },
        ]
        for config in bad:
            with self.subTest(config=config), self.assertRaises(ValueError):
                await self._run(config=config, devices=[_iface_device()])
