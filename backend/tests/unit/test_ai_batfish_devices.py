"""``list_snapshot_devices`` and ``get_ip_owners``: the devices of a snapshot with their IPs, and
the flat IP table, without paging through interface rows.

A fake reader stands in for the coordinator; nothing here talks to Batfish.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore
from services.ai_assistant.tools.base import Toolbox, ToolContext
from services.ai_assistant.tools.batfish_shaping import shape_ip_owners, shape_snapshot_devices
from services.ai_assistant.tools.batfish_tools import (
    BATFISH_READER_KEY,
    BatfishAccessError,
    BatfishAnswer,
    BatfishInputError,
    BatfishUnavailableError,
    DeviceListing,
    build_batfish_tools,
)
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY, build_result_tools
from tests.unit.test_ai_batfish_tools import FakeReader

ALL = SharingPolicy(inventory=True, addresses=True, content=True)
INVENTORY_ONLY = SharingPolicy(inventory=True)

NODES: list[dict[str, Any]] = [
    {"Node": "lab", "Configuration_Format": "CISCO_IOS", "Domain_Name": "local.zz"},
    {"Node": "r1", "Configuration_Format": "JUNIPER", "Domain_Name": None},
    {"Node": "empty", "Configuration_Format": "CISCO_IOS"},
]


def _ip(
    node: str, interface: str, ip: str, mask: int = 24, *, active: bool = True
) -> dict[str, Any]:
    return {
        "Node": node,
        "VRF": "default",
        "Interface": interface,
        "IP": ip,
        "Mask": mask,
        "Active": active,
    }


IPS: list[dict[str, Any]] = [
    _ip("lab", "Loopback0", "1.1.1.1", 32),
    _ip("lab", "Gi0/1", "10.0.0.1"),
    _ip("lab", "Gi0/2", "10.0.1.1", active=False),
    _ip("r1", "ge-0/0/0", "10.0.0.2"),
]


# -- shaping ----------------------------------------------------------------------------------


def test_one_row_per_device_with_ip_counts_and_a_sample() -> None:
    rows, summary = shape_snapshot_devices(NODES, IPS, with_ips=True, max_ips=10)

    assert [r["Node"] for r in rows] == ["empty", "lab", "r1"]
    lab = next(r for r in rows if r["Node"] == "lab")
    assert lab["Configuration_Format"] == "CISCO_IOS" and lab["Domain_Name"] == "local.zz"
    assert lab["IP_Count"] == 3 and lab["IP_Count_Inactive"] == 1 and lab["Interfaces_With_IP"] == 3
    assert lab["IPs"] == ["1.1.1.1/32", "10.0.0.1/24", "10.0.1.1/24"]
    empty = next(r for r in rows if r["Node"] == "empty")
    assert empty["IP_Count"] == 0 and empty["IPs"] == []
    assert "Domain_Name" not in empty  # absent or null: left out
    assert summary == {
        "devices": 3,
        "devices_with_ips": 2,
        "ips": 4,
        "by_configuration_format": {"CISCO_IOS": 2, "JUNIPER": 1},
    }


def test_the_count_is_of_distinct_addresses_like_the_sample() -> None:
    owned = [
        _ip("lab", "Gi0/1", "10.0.0.1"),
        _ip("lab", "Gi0/2", "10.0.0.1"),  # the same address on a second interface
        _ip("lab", "Gi0/3", "10.0.1.1", active=False),
        {"Node": "lab", "Interface": "Gi0/4", "Active": True},  # no IP at all
    ]

    rows, summary = shape_snapshot_devices(NODES[:1], owned, with_ips=True, max_ips=10)

    assert rows[0]["IP_Count"] == len(rows[0]["IPs"]) == 2
    assert rows[0]["IP_Count_Inactive"] == 1
    assert rows[0]["Interfaces_With_IP"] == 3
    assert summary["ips"] == 2


def test_the_ip_sample_is_bounded_but_the_count_is_not() -> None:
    many = [_ip("lab", f"Gi0/{n}", f"10.0.{n}.1") for n in range(30)]

    rows, _ = shape_snapshot_devices(NODES[:1], many, with_ips=True, max_ips=10)

    assert rows[0]["IP_Count"] == 30 and len(rows[0]["IPs"]) == 10


def test_without_addresses_there_are_no_ip_columns_at_all() -> None:
    rows, summary = shape_snapshot_devices(NODES, IPS, with_ips=False, max_ips=10)

    assert all(
        not {"IPs", "IP_Count", "IP_Count_Inactive", "Interfaces_With_IP"} & r.keys() for r in rows
    )
    assert "ips" not in summary and "devices_with_ips" not in summary
    assert "10.0.0.1" not in json.dumps(rows)


def test_ip_rows_for_unlisted_devices_and_missing_columns_do_not_fail() -> None:
    rows, _ = shape_snapshot_devices(
        [{"Node": "a"}],
        [{"Node": "ghost", "IP": "9.9.9.9"}, {"Node": "a", "IP": "1.2.3.4"}],
        with_ips=True,
        max_ips=10,
    )

    assert [r["Node"] for r in rows] == ["a"]
    assert rows[0]["IPs"] == ["1.2.3.4"]  # no mask: the bare address


def test_ip_owner_rows_keep_the_useful_columns_and_filter_by_node() -> None:
    rows = shape_ip_owners(IPS + [{"Node": "lab", "Internal": 1, **_ip("lab", "x", "2.2.2.2")}])

    assert set(rows[0]) == {"Node", "VRF", "Interface", "IP", "Mask", "Active"}
    assert len(rows) == 5


def test_shaping_never_mutates_its_input() -> None:
    before = json.dumps([NODES, IPS], sort_keys=True)
    shape_snapshot_devices(NODES, IPS, with_ips=True, max_ips=2)
    shape_ip_owners(IPS)

    assert json.dumps([NODES, IPS], sort_keys=True) == before


# -- the tools ---------------------------------------------------------------------------------


class DevicesFake(FakeReader):
    def __init__(self) -> None:
        super().__init__()
        self.listing = DeviceListing(
            snapshot="run-2", snapshot_created="2026-11-01T10:00:00Z", node_rows=NODES, ip_rows=IPS
        )

    async def snapshot_devices(
        self, source_id: str, network: str, snapshot: str | None, nodes: list[str], with_ips: bool
    ) -> DeviceListing:
        self.calls.append(
            ("snapshot_devices", source_id, network, snapshot, tuple(nodes), with_ips)
        )
        if self.error:
            raise self.error
        return self.listing


class DeviceToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.reader = DevicesFake()
        self.store = ResultStore(InMemoryResultBackend())

    async def _call(self, name: str, sharing: SharingPolicy = ALL, **args: Any) -> tuple[Any, Any]:
        ctx = ToolContext(
            user_id=1,
            redactor=Redactor(),
            extras={BATFISH_READER_KEY: self.reader, RESULT_STORE_KEY: self.store},
            sharing=sharing,
        )
        box = Toolbox([*build_batfish_tools(), *build_result_tools()], ctx)
        out = await box.execute(ToolCall("1", name, args))
        try:
            return out, json.loads(out.content)
        except ValueError:
            return out, None

    async def test_devices_come_back_with_a_summary_and_the_snapshot(self) -> None:
        out, data = await self._call("list_snapshot_devices", network="net1")

        assert not out.is_error, out.content
        assert [r["Node"] for r in data["rows"]] == ["empty", "lab", "r1"]
        assert data["summary"]["devices"] == 3 and data["summary"]["ips"] == 4
        assert data["snapshot"] == "run-2" and data["snapshot_created"] == "2026-11-01T10:00:00Z"
        assert self.reader.calls[-1] == ("snapshot_devices", "lab", "net1", None, (), True)

    async def test_the_ip_question_is_not_asked_without_the_addresses_opt_in(self) -> None:
        _, data = await self._call("list_snapshot_devices", INVENTORY_ONLY, network="net1")

        assert self.reader.calls[-1][-1] is False
        assert "IPs" not in json.dumps(data["rows"])
        assert "addresses" in data["note"].lower()

    async def test_without_the_inventory_opt_in_nothing_is_read(self) -> None:
        _, data = await self._call("list_snapshot_devices", SharingPolicy(), network="net1")

        assert "not_shared" in json.dumps(data)
        assert self.reader.calls == []

    async def test_a_device_filter_and_ips_off_are_forwarded(self) -> None:
        await self._call(
            "list_snapshot_devices", network="net1", nodes=["LAB.local.zz"], include_ips=False
        )

        assert self.reader.calls[-1] == (
            "snapshot_devices",
            "lab",
            "net1",
            None,
            ("LAB.local.zz",),
            False,
        )

    async def test_the_ip_sample_is_noted_as_a_sample(self) -> None:
        self.reader.listing = DeviceListing(
            snapshot="run-2",
            snapshot_created=None,
            node_rows=NODES[:1],
            ip_rows=[_ip("lab", f"Gi0/{n}", f"10.0.{n}.1") for n in range(30)],
        )

        _, data = await self._call("list_snapshot_devices", network="net1")

        assert data["rows"][0]["IP_Count"] == 30 and len(data["rows"][0]["IPs"]) == 10
        assert "first 10" in data["note"]

    async def test_a_failed_ip_question_is_named_not_hidden(self) -> None:
        self.reader.listing = DeviceListing(
            snapshot="run-2",
            snapshot_created=None,
            node_rows=NODES,
            ip_rows=[],
            unavailable={"ips": "BatfishAPIError"},
        )

        _, data = await self._call("list_snapshot_devices", network="net1")

        assert data["unavailable_sections"] == ["ips"]
        assert "ips" in data["note"] and "IP_Count" not in json.dumps(data["rows"])

    async def test_an_ip_only_cut_still_sets_the_flags_the_model_is_told_to_trust(self) -> None:
        self.reader.listing = DeviceListing(
            snapshot="run-2",
            snapshot_created=None,
            node_rows=NODES,
            ip_rows=IPS,
            truncated_sections=("ips",),
        )

        _, data = await self._call("list_snapshot_devices", network="net1")

        assert data["truncated"] is True
        assert data["total_rows_exact"] is False
        assert data["summary_complete"] is False

    async def test_the_sample_note_is_not_shown_when_every_distinct_address_is_listed(self) -> None:
        self.reader.listing = DeviceListing(
            snapshot="run-2",
            snapshot_created=None,
            node_rows=NODES[:1],
            ip_rows=[_ip("lab", "Gi0/1", "10.0.0.1"), _ip("lab", "Gi0/2", "10.0.0.1")],
        )

        _, data = await self._call("list_snapshot_devices", network="net1")

        assert data["rows"][0]["IP_Count"] == 1
        assert "note" not in data

    async def test_named_devices_with_no_result_are_an_error_not_an_empty_snapshot(self) -> None:
        self.reader.listing = DeviceListing(
            snapshot="run-2", snapshot_created=None, node_rows=[], ip_rows=[]
        )

        out, _ = await self._call("list_snapshot_devices", network="net1", nodes=["typo"])

        assert out.is_error
        assert "typo" in out.content and "not" in out.content.lower()

    async def test_an_empty_snapshot_without_a_filter_is_a_normal_answer(self) -> None:
        self.reader.listing = DeviceListing(
            snapshot="run-2", snapshot_created=None, node_rows=[], ip_rows=[]
        )

        out, data = await self._call("list_snapshot_devices", network="net1")

        assert not out.is_error and data["rows"] == [] and data["summary"]["devices"] == 0

    async def test_a_cut_answer_marks_the_counts_as_lower_bounds(self) -> None:
        self.reader.listing = DeviceListing(
            snapshot="run-2",
            snapshot_created=None,
            node_rows=NODES,
            ip_rows=IPS,
            truncated_sections=("ips",),
        )

        _, data = await self._call("list_snapshot_devices", network="net1")

        assert data["summary_complete"] is False and "at least" in data["note"]

    async def test_reader_errors_become_safe_tool_errors(self) -> None:
        for exc, fragment in (
            (BatfishInputError("No device 'x'"), "No device 'x'"),
            (BatfishAccessError(), "not available"),
            (BatfishUnavailableError(), "not reachable"),
        ):
            self.reader.error = exc
            out, _ = await self._call("list_snapshot_devices", network="net1")
            assert out.is_error and fragment in out.content

    async def test_many_devices_are_stored_behind_a_handle(self) -> None:
        self.reader.listing = DeviceListing(
            snapshot="run-2",
            snapshot_created=None,
            node_rows=[
                {"Node": f"sw{n:03d}", "Configuration_Format": "CISCO_IOS"} for n in range(120)
            ],
            ip_rows=[],
        )

        _, data = await self._call("list_snapshot_devices", network="net1")

        assert data["total_rows"] == 120 and data["handle"] and len(data["rows"]) == 20
        assert data["summary"]["devices"] == 120

    async def test_inputs_are_bounded(self) -> None:
        for bad in ({"network": "n", "nodes": ["a"] * 11}, {"network": "n", "x": 1}, {}):
            out, _ = await self._call("list_snapshot_devices", **bad)
            assert out.is_error, bad

    # -- get_ip_owners ----------------------------------------------------------------------

    async def test_ip_owners_asks_the_query_path_and_returns_the_flat_table(self) -> None:
        self.reader.answer = BatfishAnswer(rows=IPS, snapshot="run-2", snapshot_created="t")

        _, data = await self._call("get_ip_owners", network="net1", nodes=["lab"], ip="10.0.0.0/24")

        assert [r["Interface"] for r in data["rows"]][:2] == ["Loopback0", "Gi0/1"]
        kind, _, _, _, params = self.reader.calls[-1][1:6]
        assert kind == "ip_owners"
        assert params == {"nodes": "lab", "ips": "10.0.0.0/24", "duplicates_only": False}

    async def test_ip_owners_needs_the_addresses_opt_in(self) -> None:
        _, data = await self._call("get_ip_owners", INVENTORY_ONLY, network="net1")

        assert "not_shared" in json.dumps(data)

    async def test_ip_owners_validates_the_address(self) -> None:
        for bad in ("not-an-ip", "10.0.0.0/33", "10.0.0.1 or evil", "/.*/"):
            out, _ = await self._call("get_ip_owners", network="net1", ip=bad)
            assert out.is_error, bad
        assert self.reader.calls == []

    async def test_an_empty_node_filtered_table_does_not_say_the_device_owns_nothing(self) -> None:
        self.reader.answer = BatfishAnswer(rows=[], snapshot="run-2", snapshot_created="t")

        _, data = await self._call("get_ip_owners", network="net1", nodes=["lab"])

        assert data["rows"] == []
        assert "check the name" in data["note"].lower()

    async def test_an_empty_answer_from_a_cut_snapshot_says_it_may_be_incomplete(self) -> None:
        self.reader.answer = BatfishAnswer(
            rows=[], snapshot="run-2", snapshot_created="t", truncated=True
        )

        _, data = await self._call("get_ip_owners", network="net1", nodes=["lab"])

        assert "cut" in data["note"].lower() and "may" in data["note"].lower()

    async def test_the_tool_text_says_what_duplicates_with_nodes_means(self) -> None:
        spec = next(t for t in build_batfish_tools() if t.name == "get_ip_owners")

        assert "every owner" in spec.description

    async def test_duplicates_only_is_forwarded(self) -> None:
        await self._call("get_ip_owners", network="net1", duplicates_only=True)

        assert self.reader.calls[-1][5]["duplicates_only"] is True
