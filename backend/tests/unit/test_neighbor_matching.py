"""Matching neighbours to the inventory and reconciling sources (doc/AI_TOOL_CHAIN.md §24.11)."""

from __future__ import annotations

import asyncio

import pytest

from services.ai_assistant.neighbors import matching as m


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("sw2.example.com(FOC1234)", ["sw2.example.com", "sw2"]),
        ("SW2.Example.COM", ["sw2.example.com", "sw2"]),
        ("r2", ["r2"]),
        ("10.1.2.3", ["10.1.2.3"]),
        ("0011.2233.4455", ["0011.2233.4455"]),
        ("00:11:22:33:44:55", ["00:11:22:33:44:55"]),
        ("  ", []),
        ("", []),
    ],
)
def test_candidate_names(raw: str, expected: list[str]) -> None:
    assert m.candidate_names(raw) == expected


def _lookups(outcomes: dict[str, m.Lookup]):
    asked: list[str] = []

    async def resolve(name: str) -> m.Lookup:
        asked.append(name)
        return outcomes.get(name, m.Lookup("none"))

    return resolve, asked


def test_a_neighbour_is_matched_by_the_full_name_first() -> None:
    resolve, asked = _lookups({"sw2.example.com": m.Lookup("match", "sw2.example.com")})
    records = [
        {"layer": "l2", "neighbor_name": "sw2.example.com(FOC1)"},
        {"layer": "l2", "neighbor_name": "ghost"},
        {"layer": "l3", "protocol": "ospf", "neighbor_ip": "10.0.0.1"},
    ]

    result = asyncio.run(m.match_inventory(records, resolve))

    assert result[0]["inventory"] == {"matched": True, "device": "sw2.example.com", "how": "name"}
    assert result[1]["inventory"] == {"matched": False}
    assert "inventory" not in result[2]
    assert asked == ["sw2.example.com", "ghost"]
    assert "inventory" not in records[0]  # the input is not changed


def test_a_match_on_the_host_part_only_says_so() -> None:
    resolve, _ = _lookups({"sw2": m.Lookup("match", "SW2")})

    [result] = asyncio.run(
        m.match_inventory([{"layer": "l2", "neighbor_name": "sw2.other.example"}], resolve)
    )

    verdict = result["inventory"]
    assert (verdict["matched"], verdict["device"], verdict["how"]) == (True, "SW2", "short_name")
    assert "host part" in verdict["note"]


@pytest.mark.parametrize(
    ("status", "fragment"),
    [("ambiguous", "more than one"), ("unknown", "could not be searched")],
)
def test_an_unclear_lookup_is_not_a_match(status: str, fragment: str) -> None:
    resolve, asked = _lookups({"sw2.example.com": m.Lookup(status)})  # type: ignore[arg-type]

    [result] = asyncio.run(
        m.match_inventory([{"layer": "l2", "neighbor_name": "sw2.example.com"}], resolve)
    )

    assert result["inventory"]["matched"] is None
    assert fragment in result["inventory"]["note"]
    assert asked == ["sw2.example.com"]  # the short name is not tried after an unclear answer


def test_the_same_neighbour_is_looked_up_once_and_the_lookups_are_capped() -> None:
    calls = 0

    async def resolve(name: str) -> m.Lookup:
        nonlocal calls
        calls += 1
        return m.Lookup("none")

    records = [{"layer": "l2", "neighbor_name": "a"}] * 3 + [
        {"layer": "l2", "neighbor_name": f"n{i}"} for i in range(m.MAX_LOOKUPS + 10)
    ]

    result = asyncio.run(m.match_inventory(records, resolve))

    assert calls == m.MAX_LOOKUPS
    assert result[-1]["inventory"] == {"matched": None, "note": "not looked up (limit)"}


def test_a_failing_lookup_is_unmatched_not_an_error() -> None:
    async def resolve(name: str) -> m.Lookup:
        raise RuntimeError("boom")

    [result] = asyncio.run(m.match_inventory([{"layer": "l2", "neighbor_name": "x"}], resolve))

    assert result["inventory"] == {"matched": None, "note": "lookup failed"}


LIVE = [
    {
        "layer": "l2",
        "local_interface": "Gi1/0/1",
        "neighbor_name": "sw2.example.com(F1)",
        "neighbor_interface": "GigabitEthernet0/24",
    },
    {
        "layer": "l2",
        "local_interface": "Gi1/0/2",
        "neighbor_name": "r3",
        "neighbor_interface": "Gi0/0",
    },
    {
        "layer": "l2",
        "local_interface": "Gi1/0/3",
        "neighbor_name": "sw9",
        "neighbor_interface": "Gi0/1",
    },
]
DOCUMENTED = [
    {
        "local_interface": "GigabitEthernet1/0/1",
        "remote_device": "SW2",
        "remote_interface": "Gi0/24",
    },
    {"local_interface": "Gi1/0/2", "remote_device": "r4", "remote_interface": "Gi0/0"},
    {"local_interface": "Gi1/0/5", "remote_device": "sw7", "remote_interface": "Gi0/2"},
]


def test_reconcile_classifies_each_pair() -> None:
    result = m.reconcile(LIVE, DOCUMENTED)

    assert [r["local_interface"] for r in result["confirmed"]] == ["Gi1/0/1"]
    assert [r["local_interface"] for r in result["conflict"]] == ["Gi1/0/2"]
    assert result["conflict"][0]["live"] == "r3 Gi0/0"
    assert result["conflict"][0]["documented"] == "r4 Gi0/0"
    assert [r["local_interface"] for r in result["undocumented"]] == ["Gi1/0/3"]
    assert [r["local_interface"] for r in result["not_seen_live"]] == ["Gi1/0/5"]
    assert result["counts"] == {
        "confirmed": 1,
        "conflict": 1,
        "undocumented": 1,
        "not_seen_live": 1,
    }


def test_a_missing_remote_interface_compares_the_device_only() -> None:
    live = [
        {"layer": "l2", "local_interface": "Gi1", "neighbor_name": "sw2", "neighbor_interface": ""}
    ]
    documented = [
        {"local_interface": "Gi1", "remote_device": "sw2.example.com", "remote_interface": "Gi0/1"}
    ]

    assert m.reconcile(live, documented)["counts"]["confirmed"] == 1


def test_only_l2_records_take_part() -> None:
    live = [{"layer": "l3", "protocol": "ospf", "interface": "Gi1"}]

    assert m.reconcile(live, [])["counts"] == {
        "confirmed": 0,
        "conflict": 0,
        "undocumented": 0,
        "not_seen_live": 0,
    }


def test_documented_items_are_read_from_list_interfaces() -> None:
    answer = {
        "items": [
            {
                "name": "Gi1/0/1",
                "cable": {"id": "c1"},
                "connected_to": {"device": "sw2", "device_id": "d", "interface": "Gi0/24"},
            },
            {"name": "Gi1/0/2", "cable": {"id": "c2"}},
            {"name": "Gi1/0/3"},
        ]
    }

    assert m.documented_from_interfaces(answer) == [
        {"local_interface": "Gi1/0/1", "remote_device": "sw2", "remote_interface": "Gi0/24"}
    ]
    assert m.documented_from_interfaces({}) == []


def _l2(protocol: str, port: str, name: str, interface: str = "Gi0/1") -> dict:
    return {
        "layer": "l2",
        "protocol": protocol,
        "local_interface": port,
        "neighbor_name": name,
        "neighbor_interface": interface,
    }


DOC_SW2 = [{"local_interface": "Gi1", "remote_device": "sw2", "remote_interface": "Gi0/1"}]


def test_cdp_and_lldp_for_one_port_are_both_compared() -> None:
    """An LLDP row with a weak name must not overwrite the CDP row that matches."""
    live = [_l2("cdp", "Gi1", "sw2"), _l2("lldp", "Gi1", "0011.2233.4455")]

    result = m.reconcile(live, DOC_SW2)

    assert result["counts"]["confirmed"] == 1 and result["counts"]["conflict"] == 0
    [item] = result["confirmed"]
    assert item["live_sources_differ"] is True
    assert item["live"] == "cdp: sw2 Gi0/1; lldp: 0011.2233.4455 Gi0/1"


def test_the_order_of_cdp_and_lldp_does_not_matter() -> None:
    live = [_l2("lldp", "Gi1", "0011.2233.4455"), _l2("cdp", "Gi1", "sw2")]

    assert m.reconcile(live, DOC_SW2)["counts"]["confirmed"] == 1


def test_a_port_is_a_conflict_only_when_no_live_record_agrees() -> None:
    live = [_l2("cdp", "Gi1", "sw9"), _l2("lldp", "Gi1", "sw8")]

    result = m.reconcile(live, DOC_SW2)

    assert result["counts"]["conflict"] == 1
    assert result["conflict"][0]["live_sources_differ"] is True


def test_agreeing_cdp_and_lldp_do_not_raise_the_flag() -> None:
    live = [_l2("cdp", "Gi1", "sw2.example.com"), _l2("lldp", "Gi1", "sw2")]

    [item] = m.reconcile(live, DOC_SW2)["confirmed"]

    assert "live_sources_differ" not in item


def test_an_incomplete_documentation_makes_no_claim_about_missing_ports() -> None:
    live = [_l2("cdp", "Gi1", "sw2"), _l2("cdp", "Gi9", "sw9")]
    documented = [
        *DOC_SW2,
        {"local_interface": "Gi5", "remote_device": "x", "remote_interface": ""},
    ]

    result = m.reconcile(live, documented, complete=False)

    assert result["complete"] is False
    assert result["counts"] == {"confirmed": 1, "conflict": 0, "not_compared": 1}
    assert "undocumented" not in result and "not_seen_live" not in result
    assert [r["local_interface"] for r in result["not_compared"]] == ["Gi9"]


def test_a_complete_documentation_is_flagged_complete() -> None:
    assert m.reconcile([], [])["complete"] is True
