"""BGP learn result (doc/plans/BGP_PLAYBOOK.md step 3): the merge and ``get_bgp_learn_result``."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

import pytest

from services.ai_assistant.data_sharing import DataClass, SharingPolicy
from services.ai_assistant.device_exec_service import _shape_blocks
from services.ai_assistant.learn import bgp_records as br
from services.ai_assistant.output_parser import ParsedCommand
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore, StoredResult
from services.ai_assistant.tools.base import ToolContext, ToolOutput
from services.ai_assistant.tools.bgp_learn_tools import build_bgp_learn_tools
from services.ai_assistant.tools.device_tools import GENIE_PARSER_KEY
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY

USER = 7
SUMMARY_CMD = "show bgp all summary"
NEIGHBORS_CMD = "show bgp all neighbors"

SUMMARY = {
    "bgp_id": 65000,
    "vrf": {
        "default": {
            "neighbor": {
                "192.168.178.241": {
                    "address_family": {
                        "ipv4 unicast": {
                            "version": 4,
                            "as": 65000,
                            "msg_rcvd": 50,
                            "msg_sent": 52,
                            "tbl_ver": 3,
                            "input_queue": 0,
                            "output_queue": 0,
                            "up_down": "00:40:11",
                            "state_pfxrcd": "2",
                            "route_identifier": "192.168.178.240",
                        }
                    }
                },
                "192.168.178.250": {
                    "address_family": {
                        "ipv4 unicast": {
                            "version": 4,
                            "as": 65001,
                            "msg_rcvd": 0,
                            "msg_sent": 0,
                            "tbl_ver": 1,
                            "input_queue": 0,
                            "output_queue": 0,
                            "up_down": "never",
                            "state_pfxrcd": "Active",
                            "route_identifier": "192.168.178.240",
                        }
                    }
                },
            }
        }
    },
}

NEIGHBORS = {
    "vrf": {
        "default": {
            "neighbor": {
                "192.168.178.241": {
                    "remote_as": 65000,
                    "link": "internal",
                    "shutdown": False,
                    "session_state": "established",
                    "description": "peer\x1b[31m-one",
                    "bgp_negotiated_keepalive_timers": {"keepalive_interval": 60, "hold_time": 180},
                    "bgp_session_transport": {
                        "connection": {
                            "established": 1,
                            "dropped": 0,
                            "last_reset": "never",
                        }
                    },
                    "address_family": {"ipv4 unicast": {"session_state": "established"}},
                },
                "192.168.178.99": {
                    "remote_as": 65009,
                    "link": "external",
                    "shutdown": True,
                    "address_family": {"ipv4 unicast": {}},
                },
            }
        }
    }
}


def _entries(**overrides: Any) -> list[ParsedCommand]:
    parsed = {SUMMARY_CMD: SUMMARY, NEIGHBORS_CMD: NEIGHBORS, **overrides}
    return [ParsedCommand(c, p, None) for c, p in parsed.items()]


def test_summary_and_neighbors_are_merged_per_neighbor_and_family() -> None:
    facts, records, errors = br.summarize_bgp(_entries())

    assert errors == []
    assert facts == {"local_as": "65000", "router_ids": ["192.168.178.240"]}
    by_neighbor = {r["neighbor"]: r for r in records}
    assert set(by_neighbor) == {"192.168.178.241", "192.168.178.250", "192.168.178.99"}
    up = by_neighbor["192.168.178.241"]
    assert (up["state"], up["prefixes_received"], up["type"]) == ("Established", 2, "internal")
    assert (up["hold_time"], up["keepalive"], up["last_reset"]) == (180, 60, "never")
    assert up["address_family"] == "ipv4 unicast" and up["vrf"] == "default"
    down = by_neighbor["192.168.178.250"]
    assert (down["state"], down["prefixes_received"]) == ("Active", None)


def test_neighbor_missing_from_the_summary_is_kept_with_a_null_state() -> None:
    _, records, _ = br.summarize_bgp(_entries())

    shut = next(r for r in records if r["neighbor"] == "192.168.178.99")
    assert shut["state"] is None and shut["shutdown"] is True
    assert shut["remote_as"] == "65009" and shut["address_family"] == "ipv4 unicast"


def test_description_is_cleaned_of_control_characters() -> None:
    _, records, _ = br.summarize_bgp(_entries())

    desc = next(r for r in records if r["neighbor"] == "192.168.178.241")["description"]
    assert "\x1b" not in desc and desc.startswith("peer")


def test_a_failed_command_is_listed_and_the_other_half_still_counts() -> None:
    entries = [
        ParsedCommand(SUMMARY_CMD, SUMMARY, None),
        ParsedCommand(NEIGHBORS_CMD, None, "Genie could not parse this output"),
    ]

    facts, records, errors = br.summarize_bgp(entries)

    assert errors == [{"command": NEIGHBORS_CMD, "error": "Genie could not parse this output"}]
    assert facts["local_as"] == "65000" and len(records) == 2
    assert all(r["type"] is None for r in records)


def test_other_commands_and_odd_shapes_are_ignored_not_raised() -> None:
    weird = {"vrf": {"default": {"neighbor": {"1.1.1.1": {"address_family": "x"}}}}, "bgp_id": []}
    entries = [
        ParsedCommand("show bgp all detail", {"anything": 1}, None),
        ParsedCommand(SUMMARY_CMD, weird, None),
        ParsedCommand(NEIGHBORS_CMD, {"vrf": 3}, None),
    ]

    facts, records, errors = br.summarize_bgp(entries)

    assert records == [] and errors == [] and facts["local_as"] is None


@pytest.mark.parametrize(
    ("pfx", "expected"),
    [("0", ("Established", 0)), ("idle", ("Idle", None)), ("OpenSent", ("OpenSent", None))],
)
def test_state_column(pfx: str, expected: tuple[str, int | None]) -> None:
    assert br._state(pfx) == expected


def test_vrf_commands_are_recognised() -> None:
    assert br.is_summary_command("show bgp vrf BLUE all summary")
    assert br.is_neighbors_command("show bgp ipv4 unicast vrf BLUE neighbors")
    assert not br.is_neighbors_command("show bgp vrf BLUE all neighbors")  # no Genie parser
    assert not br.is_neighbors_command("show bgp ipv4 unicast vrf BLUE neighbors 1.1.1.1 policy")
    assert not br.is_summary_command("show bgp all summary | count")
    assert not br.is_neighbors_command("show bgp all neighbors 1.1.1.1 policy")


# -- the tool ----------------------------------------------------------------------------------


class FakeGenie:
    def __init__(self, answers: dict[str, Any]):
        self.answers = answers
        self.calls: list[list[str]] = []

    async def parse(self, os_name: str, outputs: Sequence[tuple[str, str]]) -> list[ParsedCommand]:
        self.calls.append([c for c, _ in outputs])
        return [
            ParsedCommand(c, self.answers.get(c), None if c in self.answers else "x")
            for c, _ in outputs
        ]


@pytest.fixture
def store() -> ResultStore:
    return ResultStore(InMemoryResultBackend())


def _store_run(store: ResultStore, commands: list[str], **meta: Any) -> str:
    text, _, spans = _shape_blocks([(c, f"text of {c}") for c in commands], lambda v: v)
    full = {
        "commands": commands,
        "spans": spans,
        "parser": "genie",
        "network_driver": "cisco_ios",
        "platform": "cisco_ios",
        **meta,
    }
    return asyncio.run(
        store.put(USER, StoredResult("device_command", DataClass.CONTENT, text=text, meta=full))
    )


def _call(store: ResultStore, genie: Any, handle: str) -> ToolOutput:
    extras: dict[str, Any] = {RESULT_STORE_KEY: store}
    if genie is not None:
        extras[GENIE_PARSER_KEY] = genie
    ctx = ToolContext(
        user_id=USER,
        redactor=Redactor(),
        extras=extras,
        sharing=SharingPolicy(inventory=True, addresses=True, content=True),
    )
    tool = build_bgp_learn_tools()[0]
    return asyncio.run(tool.handler(ctx, tool.input_model(handle=handle)))


COMMANDS = [SUMMARY_CMD, NEIGHBORS_CMD, "show bgp all cluster-ids", "show bgp all detail"]


def test_tool_parses_only_summary_and_neighbors_and_returns_the_table(store) -> None:
    genie = FakeGenie({SUMMARY_CMD: SUMMARY, NEIGHBORS_CMD: NEIGHBORS})
    out = _call(store, genie, _store_run(store, COMMANDS))

    assert not out.is_error
    assert genie.calls == [[SUMMARY_CMD], [NEIGHBORS_CMD]]  # the big table is never sent
    body = json.loads(out.content)
    assert body["facts"]["local_as"] == "65000" and body["neighbors"] == 3
    assert {r["neighbor"] for r in body["rows"]} >= {"192.168.178.241"}


def test_tool_needs_genie_and_an_output_confirmed_for_genie(store) -> None:
    handle = _store_run(store, COMMANDS)
    assert _call(store, None, handle).is_error
    other = _store_run(store, COMMANDS, parser="textfsm")
    assert _call(store, FakeGenie({}), other).is_error


def test_tool_refuses_an_output_that_is_not_a_bgp_learn(store) -> None:
    out = _call(store, FakeGenie({}), _store_run(store, ["show version"]))

    assert out.is_error and "BGP learn" in out.content


def test_tool_reports_a_command_that_did_not_parse(store) -> None:
    out = _call(store, FakeGenie({SUMMARY_CMD: SUMMARY}), _store_run(store, COMMANDS))

    body = json.loads(out.content)
    assert [e["command"] for e in body["errors"]] == [NEIGHBORS_CMD]


def test_tool_follows_a_parsed_handle_back_to_the_raw_output(store) -> None:
    raw = _store_run(store, COMMANDS)
    parsed = asyncio.run(
        store.put(
            USER,
            StoredResult(
                "parsed_output",
                DataClass.CONTENT,
                rows=[{"_command": SUMMARY_CMD, "parsed": SUMMARY}],
                meta={"parser": "genie", "source_handle": raw},
            ),
        )
    )
    genie = FakeGenie({SUMMARY_CMD: SUMMARY, NEIGHBORS_CMD: NEIGHBORS})

    out = _call(store, genie, parsed)

    assert not out.is_error and json.loads(out.content)["neighbors"] == 3


def test_a_parsed_handle_without_a_usable_source_is_refused(store) -> None:
    parsed = asyncio.run(
        store.put(
            USER,
            StoredResult(
                "parsed_output", DataClass.CONTENT, rows=[{"a": 1}], meta={"parser": "genie"}
            ),
        )
    )

    assert _call(store, FakeGenie({}), parsed).is_error


def test_a_family_only_in_the_neighbors_output_still_gets_a_row() -> None:
    neighbors = {
        "vrf": {
            "default": {
                "neighbor": {
                    "192.168.178.241": {
                        "remote_as": 65000,
                        "link": "internal",
                        "shutdown": False,
                        "address_family": {"ipv4 unicast": {}, "vpnv4 unicast": {}},
                    }
                }
            }
        }
    }

    _, records, _ = br.summarize_bgp(_entries(**{NEIGHBORS_CMD: neighbors}))

    rows = {(r["neighbor"], r["address_family"]): r for r in records}
    assert ("192.168.178.241", "vpnv4 unicast") in rows
    vpn = rows[("192.168.178.241", "vpnv4 unicast")]
    assert vpn["state"] is None and vpn["type"] == "internal"
    assert rows[("192.168.178.241", "ipv4 unicast")]["state"] == "Established"
    assert len([r for r in records if r["address_family"] == "ipv4 unicast"]) == 2  # both peers
