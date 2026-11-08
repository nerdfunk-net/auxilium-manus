"""Client data tools for Ask the Net: gates, query shaping, result shape, errors, wiring."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from services.ai_assistant.client_data_reader import ClientDataAccessError
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools.base import Toolbox, ToolContext
from services.ai_assistant.tools.client_data_tools import (
    CLIENT_DATA_READER_KEY,
    build_client_data_tools,
)

ALL = SharingPolicy(inventory=True, addresses=True)
INVENTORY_ONLY = SharingPolicy(inventory=True)
NOTHING = SharingPolicy()
HOUR_AGO = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
TWO_HOURS_AGO = (datetime.now(UTC) - timedelta(hours=2)).isoformat()


def _row(device: str, port: str, **over: Any) -> dict[str, Any]:
    row = {
        "mac_address": "aabb.ccdd.0001",
        "device_name": device,
        "port": port,
        "vlan": "10",
        "vrf": None,
        "ip_address": "10.0.0.5",
        "hostname": "pc1.example.net",
        "macs_on_port": 1,
        "is_uplink": False,
        "likely_location": False,
        "session_id": "run-1",
        "collected_at": HOUR_AGO,
        "ip_collected_at": TWO_HOURS_AGO,
    }
    row.update(over)
    return row


ROWS = [
    _row("swA", "Et0/0", macs_on_port=40, is_uplink=True),
    _row("swB", "Gi1/0/5", likely_location=True),
    _row("core1", "Vlan10", macs_on_port=None, mac_address="aabb.ccdd.0001"),
]
COVERAGE = [
    {
        "device_name": "core1",
        "collected_at": HOUR_AGO,
        "arp_collected_at": HOUR_AGO,
        "mac_collected_at": HOUR_AGO,
        "arp_status": "ok",
        "mac_status": "not_supported",
        "vrf_status": "ok",
        "vrf_count": 1,
        "arp_rows": 6,
        "mac_rows": 0,
    },
    {
        "device_name": "swB",
        "collected_at": HOUR_AGO,
        "arp_collected_at": HOUR_AGO,
        "mac_collected_at": TWO_HOURS_AGO,
        "arp_status": "ok",
        "mac_status": "ok",
        "vrf_status": "ok",
        "vrf_count": 0,
        "arp_rows": 2,
        "mac_rows": 20,
    },
]
HISTORY = {
    "ip_history": [],
    "mac_history": [
        {
            "mac_address": "aabb.ccdd.0001",
            "port": "Gi1/0/5",
            "vlan": "10",
            "device_name": "swB",
            "ip_address": "10.0.0.5",
            "collected_at": HOUR_AGO,
        }
    ],
    "hostname_history": [],
}


class FakeReader:
    def __init__(
        self,
        rows: list[dict] | None = None,
        total: int | None = None,
        error: Exception | None = None,
        coverage: list[dict] | None = None,
    ) -> None:
        self.rows = list(ROWS) if rows is None else rows
        self.total = len(self.rows) if total is None else total
        self.error = error
        self.coverage_rows = list(COVERAGE) if coverage is None else coverage
        self.calls: list[tuple[str, dict]] = []

    async def observations(self, **filters: Any):
        self.calls.append(("observations", filters))
        if self.error:
            raise self.error
        return self.rows, self.total

    async def history(self, **filters: Any):
        self.calls.append(("history", filters))
        if self.error:
            raise self.error
        return HISTORY

    async def coverage(self):
        self.calls.append(("coverage", {}))
        if self.error:
            raise self.error
        return self.coverage_rows


def _call(reader: FakeReader, name: str, sharing: SharingPolicy = ALL, **args: Any):
    ctx = ToolContext(
        user_id=1,
        redactor=Redactor(),
        extras={CLIENT_DATA_READER_KEY: reader},
        sharing=sharing,
    )
    out = asyncio.run(Toolbox(build_client_data_tools(), ctx).execute(ToolCall("1", name, args)))
    return out, (json.loads(out.content) if out.content.startswith("{") else None)


def test_the_tools_are_reads_named_for_what_they_return() -> None:
    names = [t.name for t in build_client_data_tools()]

    assert names == [
        "find_client",
        "list_clients",
        "get_client_history",
        "get_client_data_coverage",
    ]


@pytest.mark.parametrize("name", ["find_client", "list_clients", "get_client_history"])
@pytest.mark.parametrize(
    ("sharing", "withheld"), [(NOTHING, "inventory_data"), (INVENTORY_ONLY, "device_addresses")]
)
def test_address_tools_need_the_inventory_and_addresses_switches(
    name: str, sharing: SharingPolicy, withheld: str
) -> None:
    reader = FakeReader()
    args = {"mac_address": "aabb.ccdd.0001"} if name == "get_client_history" else {}
    if name == "find_client":
        args = {"address": "aabb.ccdd.0001"}

    out, data = _call(reader, name, sharing, **args)

    assert data["not_shared"] == withheld
    assert reader.calls == []  # checked before any read, so existence cannot leak
    assert out.withheld == (withheld,)


def test_coverage_needs_only_the_inventory_switch() -> None:
    reader = FakeReader()

    _, data = _call(reader, "get_client_data_coverage", INVENTORY_ONLY)
    assert data["rows"][0]["device"] == "core1"

    _, denied = _call(reader, "get_client_data_coverage", NOTHING)
    assert denied["not_shared"] == "inventory_data"


@pytest.mark.parametrize(
    ("address", "filter_name", "value"),
    [
        ("AA:BB:CC:DD:00:01", "mac_address", "AA:BB:CC:DD:00:01"),
        ("aabb.ccdd.0001", "mac_address", "aabb.ccdd.0001"),
        ("10.0.0.5", "ip_address", "10.0.0.5"),
        ("2001:db8::5", "ip_address", "2001:db8::5"),
        ("pc1.example.net", "hostname", "pc1.example.net"),
    ],
)
def test_find_client_looks_up_the_whole_value(address: str, filter_name: str, value: str) -> None:
    reader = FakeReader()

    _call(reader, "find_client", address=address)

    (kind, filters) = reader.calls[0]
    assert kind == "observations"
    assert filters[filter_name] == value
    assert filters["exact"] is True


@pytest.mark.parametrize("address", ["10.0.0.999", "999.1.1.1", "bad name!", "", "a" * 256])
def test_find_client_rejects_values_that_are_no_address_or_hostname(address: str) -> None:
    reader = FakeReader()

    out, _ = _call(reader, "find_client", address=address)

    assert out.is_error
    assert reader.calls == []


def test_find_client_puts_the_likely_location_first_and_explains_uplinks() -> None:
    out, data = _call(FakeReader(), "find_client", address="aabb.ccdd.0001")

    assert data["likely_location"]["device"] == "swB"
    assert data["likely_location"]["port"] == "Gi1/0/5"
    rows = data["rows"]
    assert [r["device"] for r in rows] == ["swB", "core1", "swA"]
    assert rows[0]["likely_location"] is True
    assert rows[2]["is_uplink"] is True
    assert "uplink" in data["note"].lower()
    assert "collected" in data["note"].lower()
    assert rows[0]["age_seconds"] >= 3600


def test_find_client_without_a_likely_location_says_so() -> None:
    only_uplink = [_row("swA", "Et0/0", macs_on_port=40, is_uplink=True)]

    _, data = _call(FakeReader(only_uplink), "find_client", address="10.0.0.5")

    assert data["likely_location"] is None
    assert "no access port" in data["note"].lower()


def test_find_client_with_no_match_is_an_answer_not_an_error() -> None:
    out, data = _call(FakeReader(rows=[]), "find_client", address="10.9.9.9")

    assert not out.is_error
    assert data["rows"] == []
    assert data["likely_location"] is None
    assert "get_client_data_coverage" in data["note"]


def test_find_client_reports_the_true_total_when_cut() -> None:
    many = [_row(f"sw{n:02d}", "Gi1/0/1") for n in range(30)]

    _, data = _call(FakeReader(many, total=30), "find_client", address="10.0.0.5")

    assert (data["total_rows"], data["truncated"], len(data["rows"])) == (30, True, 20)


def test_list_clients_defaults_to_hiding_uplinks_and_pages() -> None:
    reader = FakeReader()

    _call(reader, "list_clients", device="swB", vlan="10", page=2)

    _, filters = reader.calls[0]
    assert filters["device_name"] == "swB"
    assert filters["vlan"] == "10"
    assert filters["hide_uplinks"] is True
    assert (filters["page"], filters["page_size"]) == (2, 20)
    assert filters["exact"] is False


def test_list_clients_can_include_uplinks_and_maps_the_contains_filters() -> None:
    reader = FakeReader()

    _call(
        reader,
        "list_clients",
        mac_contains="aabb",
        ip_contains="10.0.",
        hostname_contains="pc",
        port="Gi1",
        vrf="CUST",
        hide_uplinks=False,
    )

    _, filters = reader.calls[0]
    assert (filters["mac_address"], filters["ip_address"], filters["hostname"]) == (
        "aabb",
        "10.0.",
        "pc",
    )
    assert (filters["port"], filters["vrf"], filters["hide_uplinks"]) == ("Gi1", "CUST", False)


def test_list_clients_reports_total_and_the_next_page() -> None:
    _, data = _call(FakeReader(total=45), "list_clients", page=1)

    assert (data["total_rows"], data["truncated"]) == (45, True)
    assert data["page"] == 1
    assert "page=2" in data["note"]


def test_list_clients_rejects_unknown_arguments_and_a_page_below_one() -> None:
    out, _ = _call(FakeReader(), "list_clients", bogus=1)
    assert out.is_error
    out, _ = _call(FakeReader(), "list_clients", page=0)
    assert out.is_error


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ({"mac_address": "aa:bb:cc:dd:00:01"}, "mac_address"),
        ({"ip_address": "10.0.0.5"}, "ip_address"),
        ({"hostname": "pc1.example.net"}, "hostname"),
    ],
)
def test_history_takes_exactly_one_identifier(args: dict[str, str], expected: str) -> None:
    reader = FakeReader()

    _, data = _call(reader, "get_client_history", **args)

    (_, filters) = reader.calls[0]
    assert filters[expected] == list(args.values())[0]
    assert filters["limit"] == 21  # one more than shown, to know whether it was cut
    assert data["rows"][0]["device"] == "swB"
    assert data["rows"][0]["kind"] == "mac"
    assert "retained" in data["note"].lower()


@pytest.mark.parametrize("args", [{}, {"mac_address": "aabb.ccdd.0001", "ip_address": "10.0.0.5"}])
def test_history_rejects_zero_or_several_identifiers(args: dict[str, str]) -> None:
    reader = FakeReader()

    out, _ = _call(reader, "get_client_history", **args)

    assert out.is_error
    assert reader.calls == []


def test_coverage_shows_what_each_device_could_and_could_not_provide() -> None:
    _, data = _call(FakeReader(), "get_client_data_coverage")

    core1, swb = data["rows"]
    assert core1["mac_status"] == "not_supported"
    assert (swb["arp_entries"], swb["mac_entries"]) == (2, 20)
    assert core1["age_seconds"] >= 3600
    assert data["summary"]["devices"] == 2
    assert "not_supported" in data["note"]
    # Each table has its own age: swB's MAC table is older than its ARP table.
    assert swb["arp_age_seconds"] < swb["mac_age_seconds"]
    assert swb["mac_age_seconds"] >= 7200
    assert "skipped" in data["note"]


def test_coverage_without_data_says_how_to_collect_it() -> None:
    out, data = _call(FakeReader(coverage=[]), "get_client_data_coverage")

    assert not out.is_error
    assert data["rows"] == []
    assert "Collect Client Data" in data["note"]


@pytest.mark.parametrize(
    "name", ["find_client", "list_clients", "get_client_history", "get_client_data_coverage"]
)
def test_a_user_without_client_data_read_gets_a_plain_error(name: str) -> None:
    args = {"find_client": {"address": "10.0.0.5"}, "get_client_history": {"ip_address": "1.1.1.1"}}
    reader = FakeReader(error=ClientDataAccessError())

    out, _ = _call(reader, name, **args.get(name, {}))

    assert out.is_error
    assert "client_data:read" in out.content


def test_an_unexpected_failure_leaks_nothing() -> None:
    out, _ = _call(
        FakeReader(error=RuntimeError("password=hunter2 at 10.0.0.1")),
        "find_client",
        address="10.0.0.5",
    )

    assert out.is_error
    assert "hunter2" not in out.content


# --- wiring ------------------------------------------------------------------------------------


def _general_names(**kwargs: Any) -> list[str]:
    from services.ai_assistant.surfaces import build_general_session
    from tests.unit.test_ai_batfish_tools import FakeReader as BatfishReader

    session = build_general_session(
        user_id=1,
        reader=BatfishReader(),
        store=None,
        sharing=ALL,
        may_query_batfish=False,
        **kwargs,
    )
    return [s.name for s in session.toolbox.specs()], session.system


def test_the_general_surface_offers_the_tools_only_with_a_reader() -> None:
    without, _ = _general_names()
    with_reader, system = _general_names(client_data_reader=FakeReader())

    assert not [n for n in without if "client" in n]
    assert {n for n in with_reader if "client" in n} == {
        "find_client",
        "list_clients",
        "get_client_history",
        "get_client_data_coverage",
    }
    assert "find_client" in system
    assert "client data" in system.lower()


def test_playbooks_know_the_client_data_tools() -> None:
    from services.ai_assistant.tools.playbook_tools import known_general_tool_names

    assert {"find_client", "list_clients"} <= known_general_tool_names()


# --- review findings ----------------------------------------------------------------------------


def test_find_client_asks_for_the_likely_location_first() -> None:
    reader = FakeReader()

    _call(reader, "find_client", address="aabb.ccdd.0001")

    assert reader.calls[0][1]["likely_first"] is True


@pytest.mark.parametrize("address", ["deadbeefcafe", "DEADBEEFCAFE"])
def test_a_twelve_digit_hex_name_is_tried_as_a_mac_and_then_as_a_hostname(address: str) -> None:
    class Sequential(FakeReader):
        async def observations(self, **filters: Any):
            self.calls.append(("observations", filters))
            return ([], 0) if "mac_address" in filters else (self.rows, len(self.rows))

    reader = Sequential()

    _, data = _call(reader, "find_client", address=address)

    assert [("mac_address" in f, "hostname" in f) for _, f in reader.calls] == [
        (True, False),
        (False, True),
    ]
    assert data["query"]["kind"] == "hostname"
    assert data["rows"]


def test_a_twelve_digit_hex_value_that_is_a_mac_is_not_searched_again() -> None:
    reader = FakeReader()

    _, data = _call(reader, "find_client", address="aabbccddeeff")

    assert len(reader.calls) == 1
    assert data["query"]["kind"] == "mac"


def test_history_says_when_it_was_cut_at_the_limit() -> None:
    class Many(FakeReader):
        async def history(self, **filters: Any):
            self.calls.append(("history", filters))
            entry = HISTORY["mac_history"][0]
            return {"ip_history": [], "hostname_history": [], "mac_history": [entry] * 21}

    _, data = _call(Many(), "get_client_history", mac_address="aabb.ccdd.0001")

    assert data["truncated"] is True
    assert data["total_rows_exact"] is False
    assert len(data["rows"]) == 20


def test_history_that_fits_is_complete() -> None:
    _, data = _call(FakeReader(), "get_client_history", mac_address="aabb.ccdd.0001")

    assert (data["truncated"], data["total_rows_exact"]) == (False, True)


def test_list_clients_matches_a_real_prefix_and_says_that_contains_is_text() -> None:
    reader = FakeReader()

    _call(reader, "list_clients", ip_prefix="10.1.")
    out, _ = _call(FakeReader(), "list_clients", ip_prefix="10.1.0.0/16")

    assert reader.calls[0][1]["ip_prefix"] == "10.1."
    assert out.is_error  # a CIDR is not a prefix
    description = {t.name: t.description for t in build_client_data_tools()}["list_clients"]
    assert "ip_prefix" in description
    assert "10.1.0.0/16" not in description


def test_an_observation_carries_the_age_of_its_port_and_of_its_ip() -> None:
    _, data = _call(FakeReader(), "find_client", address="aabb.ccdd.0001")

    row = data["rows"][0]
    assert row["age_seconds"] >= 3600
    assert row["ip_age_seconds"] >= 7200  # the IP is older than the port
    assert "ip_age_seconds" in data["note"]


def test_a_row_without_an_ip_has_no_ip_age() -> None:
    no_ip = [_row("swB", "Gi1/0/5", ip_address=None, ip_collected_at=None, likely_location=True)]

    _, data = _call(FakeReader(no_ip), "find_client", address="aabb.ccdd.0001")

    assert data["rows"][0]["ip_age_seconds"] is None


def test_coverage_of_many_devices_is_still_valid_json_and_continues_with_an_offset() -> None:
    many = [{**COVERAGE[1], "device_name": f"switch-with-a-long-name-{n:03d}"} for n in range(300)]

    out, data = _call(FakeReader(coverage=many), "get_client_data_coverage")

    assert data is not None  # parses
    assert data["total_rows"] == 300
    assert data["truncated"] is True
    shown = len(data["rows"])
    assert 0 < shown < 300
    assert f"offset={shown}" in data["note"]
    _, second = _call(FakeReader(coverage=many), "get_client_data_coverage", offset=shown)
    assert second["rows"][0]["device"] == f"switch-with-a-long-name-{shown:03d}"
    assert not out.is_error


def test_coverage_summarises_how_many_devices_lack_a_table() -> None:
    _, data = _call(FakeReader(), "get_client_data_coverage")

    assert data["summary"] == {
        "devices": 2,
        "arp_not_collected": 0,
        "mac_not_supported": 1,
        "mac_not_collected": 0,
    }
