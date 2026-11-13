"""The Nautobot report source: static catalog, rows read as the calling user, queried in memory."""

from __future__ import annotations

import unittest
from typing import Any

from nautobot_read.client import NautobotError, TooManyRowsError
from nautobot_read.context import QueryContext

from models.reports import ReportQuery
from services.ai_assistant.nautobot_query_reader import NautobotAccessError
from services.reports.errors import ReportQueryError
from services.reports.report_query_service import ReportQueryService
from services.reports.sources.nautobot_source import MAX_DEVICES, NautobotReportSource


def _raw(name: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": f"id-{name}",
        "name": name,
        "serial": "",
        "role": {"name": "Switch"},
        "status": {"name": "Active"},
        "device_type": {"model": "C9300", "manufacturer": {"name": "Cisco"}},
        "platform": {"name": "Cisco IOS"},
        "location": {"id": "l1", "name": "Berlin"},
        "primary_ip4": {"address": "10.0.0.1/24"},
        "tags": [{"name": "core"}, {"name": "lab"}],
    }
    row.update(over)
    return row


SOFTWARE = {
    "version": "17.9.4",
    "long_term_support": True,
    "software_image_files": [{"image_file_name": "cat9k.bin"}, {"image_file_name": "cat9k.sha"}],
}


class _Vocab:
    async def locations(self) -> Any:
        raise TooManyRowsError("too many locations")  # -> the plain location name is used


class _Client:
    def __init__(self, rows: list[dict[str, Any]] | Exception) -> None:
        self.rows = rows
        self.roots: list[str] = []
        self.calls: list[tuple[Any, ...]] = []
        self.selections: list[str] = []

    async def list_all(self, root: str, selection: str, filters: Any, *, max_items: int) -> Any:
        self.calls.append((root, filters, max_items))
        self.selections.append(selection)
        self.roots.append(root)
        if isinstance(self.rows, Exception):
            raise self.rows
        return self.rows


def source(rows: list[dict[str, Any]] | Exception, *, user: int | None = 7):
    client = _Client(rows)
    seen: list[int] = []

    async def factory(user_id: int) -> QueryContext:
        seen.append(user_id)
        return QueryContext(client=client, vocabularies=_Vocab())  # type: ignore[arg-type]

    return NautobotReportSource(None, actor_user_id=user, context_factory=factory), client, seen  # type: ignore[arg-type]


def devices(**spec: Any) -> ReportQuery:
    return ReportQuery(source="nautobot", dataset="devices", **spec)


class CatalogTests(unittest.TestCase):
    def test_catalog_is_static_and_needs_no_nautobot(self) -> None:
        src, client, seen = source([])
        dataset = src.describe()[0]
        self.assertEqual(dataset.name, "devices")
        self.assertEqual(dataset.mode, "device")
        self.assertIn("serial", [f.name for f in dataset.fields])
        self.assertEqual((client.calls, seen), ([], []))

    def test_validate_checks_fields_without_a_request(self) -> None:
        src, client, _ = source([])
        src.validate(devices(select=["serial"]))
        with self.assertRaises(ReportQueryError):
            src.validate(devices(select=["nope"]))
        with self.assertRaises(ReportQueryError):
            src.validate(ReportQuery(source="nautobot", dataset="interfaces"))
        self.assertEqual(client.calls, [])


class RunTests(unittest.TestCase):
    def test_serial_list_for_all_devices(self) -> None:
        src, client, seen = source([_raw("sw2", serial="S2"), _raw("sw1", serial="S1")])
        result = src.run(devices(select=["device_name", "serial"]))
        self.assertEqual(result.rows, [["sw1", "S1"], ["sw2", "S2"]])
        self.assertEqual(seen, [7])  # read as the calling user
        self.assertEqual(client.calls, [("devices", {}, MAX_DEVICES)])

    def test_empty_values_become_missing_and_tags_are_joined(self) -> None:
        src, _, _ = source([_raw("sw1")])
        result = src.run(devices(select=["serial", "tags"]))
        self.assertEqual(result.rows, [[None, "core, lab"]])

    def test_device_types_grouped_by_location(self) -> None:
        rows = [
            _raw("a"),
            _raw("b"),
            _raw("c", location={"id": "l2", "name": "Munich"}),
        ]
        src, _, _ = source(rows)
        result = src.run(
            devices(group_by=["location", "device_type"], metrics=[{"op": "count", "alias": "n"}])
        )
        self.assertEqual(result.rows, [["Berlin", "C9300", 2], ["Munich", "C9300", 1]])

    def test_invalid_query_is_rejected_before_nautobot_is_called(self) -> None:
        src, client, seen = source([_raw("a")])
        with self.assertRaises(ReportQueryError):
            src.run(devices(select=["nope"]))
        self.assertEqual((client.calls, seen), ([], []))

    def test_no_user_is_refused(self) -> None:
        src, _, _ = source([_raw("a")], user=None)
        with self.assertRaisesRegex(ReportQueryError, "signed-in user"):
            src.run(devices())


class SoftwareTests(unittest.TestCase):
    def test_software_version_lts_and_image_files(self) -> None:
        src, client, _ = source([_raw("sw1", software_version=SOFTWARE), _raw("sw2")])
        result = src.run(
            devices(select=["device_name", "software_version", "software_lts", "software_images"])
        )
        self.assertEqual(
            result.rows,
            [["sw1", "17.9.4", True, "cat9k.bin, cat9k.sha"], ["sw2", None, None, None]],
        )
        self.assertEqual(client.selections[0].count("software_version {"), 1)

    def test_software_summarized_by_device_type(self) -> None:
        rows = [
            _raw("a", software_version={"version": "17.9.4"}),
            _raw("b", software_version={"version": "17.9.4"}),
            _raw("c", software_version={"version": "17.6.1"}),
        ]
        src, _, _ = source(rows)
        result = src.run(
            devices(
                group_by=["device_type", "software_version"],
                metrics=[{"op": "count", "alias": "devices"}],
            )
        )
        self.assertEqual(result.rows, [["C9300", "17.6.1", 1], ["C9300", "17.9.4", 2]])


class DevicesOfASoftwareVersionTests(unittest.TestCase):
    def test_filter_on_software_version_lists_its_devices(self) -> None:
        rows = [
            _raw("a", software_version={"version": "15.0.0"}),
            _raw("b", software_version={"version": "17.9.4"}),
            _raw("c", software_version={"version": "15.0.0"}),
            _raw("d"),
        ]
        src, _, _ = source(rows)
        result = src.run(
            devices(
                select=["device_name", "device_type"],
                filters=[{"field": "software_version", "op": "eq", "value": "15.0.0"}],
            )
        )
        self.assertEqual([r[0] for r in result.rows], ["a", "c"])


class SoftwareVersionDatasetTests(unittest.TestCase):
    VERSIONS = [
        {
            "id": "1",
            "version": "15.0.0",
            "long_term_support": False,
            "platform": {"name": "Cisco IOS", "manufacturer": {"name": "Cisco"}},
            "software_image_files": [{"image_file_name": "ios15.bin"}],
            "devices": [{"id": "d1"}, {"id": "d2"}],
        },
        {
            "id": "2",
            "version": "17.9.4",
            "long_term_support": True,
            "platform": {"name": "Cisco IOS-XE", "manufacturer": {"name": "Cisco"}},
            "software_image_files": [],
            "devices": [],
        },
    ]

    def test_catalog_lists_both_datasets(self) -> None:
        src, _, _ = source([])
        by_name = {d.name: d for d in src.describe()}
        self.assertEqual(list(by_name), ["devices", "software_versions"])
        self.assertEqual(by_name["software_versions"].mode, "items")

    def test_versions_with_device_counts_including_unused(self) -> None:
        src, client, _ = source(self.VERSIONS)
        result = src.run(
            ReportQuery(
                source="nautobot",
                dataset="software_versions",
                select=[
                    "device_name",
                    "version",
                    "long_term_support",
                    "device_count",
                    "image_files",
                ],
            )
        )
        self.assertEqual(
            result.rows,
            [
                ["Cisco IOS 15.0.0", "15.0.0", False, 2, "ios15.bin"],
                ["Cisco IOS-XE 17.9.4", "17.9.4", True, 0, None],
            ],
        )
        self.assertEqual(client.roots, ["software_versions"])

    def test_unused_versions(self) -> None:
        src, _, _ = source(self.VERSIONS)
        result = src.run(
            ReportQuery(
                source="nautobot",
                dataset="software_versions",
                select=["platform", "version"],
                filters=[{"field": "device_count", "op": "lt", "value": 1}],
            )
        )
        self.assertEqual(result.rows, [["Cisco IOS-XE", "17.9.4"]])

    def test_too_many_rows_names_the_table(self) -> None:
        src, _, _ = source(TooManyRowsError("x"))
        with self.assertRaisesRegex(ReportQueryError, "more than 5000 software versions"):
            src.run(ReportQuery(source="nautobot", dataset="software_versions"))


class RowShapeTests(unittest.TestCase):
    """Review: one odd nested value must not fail the section, and a wrong shape is not a count."""

    def test_null_and_odd_nested_values_are_left_out(self) -> None:
        odd = _raw(
            "sw1",
            tags=[{"name": None}, {"name": "lab"}, "x", None],
            software_version={
                "version": "17.9.4",
                "long_term_support": "yes",
                "software_image_files": [
                    {"image_file_name": None},
                    {"image_file_name": "a.bin"},
                    5,
                ],
            },
        )
        src, _, _ = source([odd, _raw("sw2", software_version=["not", "a", "dict"], tags="lab")])
        result = src.run(devices(select=["device_name", "tags", "software_lts", "software_images"]))
        self.assertEqual(result.rows, [["sw1", "lab", None, "a.bin"], ["sw2", None, None, None]])

    def test_device_count_is_only_a_count_of_a_list(self) -> None:
        versions = [
            {"id": "1", "version": "1.0", "platform": {"name": "P"}, "devices": [{"id": "d"}]},
            # A connection-like object: len() of a dict is its number of keys, not devices.
            {
                "id": "2",
                "version": "2.0",
                "platform": {"name": "P"},
                "devices": {"edges": [], "n": 1},
            },
            {
                "id": "3",
                "version": "3.0",
                "platform": None,
                "devices": None,
                "software_image_files": [{"image_file_name": None}],
                "long_term_support": 1,
            },
        ]
        src, _, _ = source(versions)
        result = src.run(
            ReportQuery(
                source="nautobot",
                dataset="software_versions",
                select=["version", "device_count", "long_term_support", "image_files"],
            )
        )
        self.assertEqual(
            result.rows,
            [["3.0", None, None, None], ["1.0", 1, None, None], ["2.0", None, None, None]],
        )


class PushdownTests(unittest.TestCase):
    """Review: a question about one device must not read the whole table."""

    def run_with(self, rows: list[dict[str, Any]], **spec: Any):
        src, client, _ = source(rows)
        return src.run(devices(**spec)), client

    def test_name_filters_go_to_nautobot_and_are_checked_again_here(self) -> None:
        result, client = self.run_with(
            [_raw("sw1"), _raw("SW1x")],  # a looser server filter can not add a row
            select=["device_name"],
            filters=[{"field": "device_name", "op": "eq", "value": "sw1"}],
        )
        self.assertEqual(client.calls, [("devices", {"name": ["sw1"]}, MAX_DEVICES)])
        self.assertEqual(result.rows, [["sw1"]])

    def test_in_and_two_filters_on_one_field_send_the_intersection(self) -> None:
        _, client = self.run_with(
            [],
            select=["device_name"],
            filters=[
                {"field": "device_name", "op": "in", "value": ["a", "b", "c"]},
                {"field": "device_name", "op": "in", "value": ["b", "c", "d"]},
            ],
        )
        self.assertEqual(client.calls[0][1], {"name": ["b", "c"]})

    def test_contradicting_filters_match_nothing_without_a_request(self) -> None:
        result, client = self.run_with(
            [_raw("a")],
            select=["device_name"],
            filters=[
                {"field": "device_name", "op": "eq", "value": "a"},
                {"field": "device_name", "op": "eq", "value": "b"},
            ],
        )
        self.assertEqual((result.rows, client.calls), ([], []))

    def test_other_filters_are_not_sent(self) -> None:
        _, client = self.run_with(
            [],
            select=["device_name"],
            filters=[
                {"field": "device_name", "op": "contains", "value": "sw"},
                {"field": "device_name", "op": "ne", "value": "x"},
                {"field": "location", "op": "eq", "value": "Berlin"},
            ],
        )
        self.assertEqual(client.calls[0][1], {})

    def test_software_version_filter_uses_the_version_filter(self) -> None:
        src, client, _ = source([])
        src.run(
            ReportQuery(
                source="nautobot",
                dataset="software_versions",
                filters=[{"field": "version", "op": "eq", "value": "15.0.0"}],
            )
        )
        self.assertEqual(client.calls[0][1], {"version": ["15.0.0"]})


class FailureTests(unittest.TestCase):
    def check(self, failure: Exception, pattern: str) -> None:
        src, _, _ = source(failure)
        with self.assertRaisesRegex(ReportQueryError, pattern):
            src.run(devices())

    def test_too_many_devices(self) -> None:
        self.check(TooManyRowsError("x"), "more than 5000 devices")

    def test_nautobot_error_message_is_passed_on(self) -> None:
        self.check(NautobotError("Nautobot did not answer"), "did not answer")

    def test_no_access(self) -> None:
        async def refuse(_: int) -> QueryContext:
            raise NautobotAccessError

        src = NautobotReportSource(None, actor_user_id=1, context_factory=refuse)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ReportQueryError, "sources.nautobot:read"):
            src.run(devices())


class ServiceTests(unittest.TestCase):
    def test_query_service_passes_the_acting_user_to_the_source(self) -> None:
        service = ReportQueryService(None, actor_user_id=42)  # type: ignore[arg-type]
        self.assertEqual(
            [d.name for d in service.catalog("nautobot")], ["devices", "software_versions"]
        )
        self.assertEqual(service.actor_user_id, 42)


if __name__ == "__main__":
    unittest.main()


class DefaultContextTests(unittest.TestCase):
    def test_the_default_context_is_isolated_from_the_main_event_loop(self) -> None:
        import asyncio
        from unittest.mock import patch

        from services.ai_assistant import nautobot_query_reader as reader_module
        from services.reports.sources import nautobot_source

        seen: list[bool] = []

        async def fake_context(self, *, isolated: bool = False):
            seen.append(isolated)
            return "ctx"

        with patch.object(reader_module.DbNautobotQueryReader, "context", fake_context):
            self.assertEqual(asyncio.run(nautobot_source._default_context(3)), "ctx")

        self.assertEqual(seen, [True])
