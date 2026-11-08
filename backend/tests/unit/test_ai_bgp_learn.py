"""BGP learn result (doc/plans/BGP_PLAYBOOK.md step 3): the merge and ``get_bgp_learn_result``."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

import pytest

from services.ai_assistant.data_sharing import DataClass, SharingPolicy
from services.ai_assistant.device_exec_service import _shape_blocks
from services.ai_assistant.learn import bgp_compare
from services.ai_assistant.learn import bgp_records as br
from services.ai_assistant.output_parser import ParsedCommand, ParserUnavailableError
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


# -- compare_bgp_learns ------------------------------------------------------------------------


def _summary(state_pfxrcd: str, up_down: str = "00:40:11") -> dict[str, Any]:
    peer = SUMMARY["vrf"]["default"]["neighbor"]["192.168.178.241"]["address_family"][
        "ipv4 unicast"
    ]
    row = {**peer, "state_pfxrcd": state_pfxrcd, "up_down": up_down}
    return {
        "bgp_id": 65000,
        "vrf": {
            "default": {"neighbor": {"192.168.178.241": {"address_family": {"ipv4 unicast": row}}}}
        },
    }


def _neighbors(dropped: int = 0, reason: str | None = None) -> dict[str, Any]:
    connection: dict[str, Any] = {
        "established": 1 + dropped,
        "dropped": dropped,
        "last_reset": "never",
    }
    if reason:
        connection["reset_reason"] = reason
    peer = {
        **NEIGHBORS["vrf"]["default"]["neighbor"]["192.168.178.241"],
        "bgp_session_transport": {"connection": connection},
    }
    return {"vrf": {"default": {"neighbor": {"192.168.178.241": peer}}}}


class TaggedGenie:
    """Answers by the tag the stored text starts with, so two readings can differ."""

    def __init__(self, readings: dict[str, dict[str, Any]], *, replay_error: bool = False):
        self.readings = readings
        self.replay_error = replay_error
        self.replays: list[str] = []
        self.diffs: list[list[str]] = []

    async def parse(self, os_name: str, outputs: Sequence[tuple[str, str]]) -> list[ParsedCommand]:
        result = []
        for command, output in outputs:
            tag = output.split(":", 1)[0]
            answer = self.readings.get(tag, {}).get(command)
            result.append(ParsedCommand(command, answer, None if answer else "boom"))
        return result

    async def learn_replay(self, os_name, feature, outputs):
        if self.replay_error:
            raise ParserUnavailableError("The pyATS service could not parse the output")
        tag = outputs[0][1].split(":", 1)[0]
        self.replays.append(tag)
        return {"info": {"tag": tag}, "_exclude": []}

    async def diff_models(self, before, after, exclude):
        self.diffs.append(list(exclude))
        return {"identical": False, "diff": "-tag: a\n+tag: b", "excluded": list(exclude)}


def _tagged_run(store: ResultStore, tag: str, commands: list[str] = COMMANDS, **meta: Any) -> str:
    text, _, spans = _shape_blocks([(c, f"{tag}: {c}") for c in commands], lambda v: v)
    full = {
        "commands": commands,
        "spans": spans,
        "parser": "genie",
        "network_driver": "cisco_ios",
        "platform": "cisco_ios",
        "device_name": "LAB",
        "device_id": "dev-1",
        "source_id": "nb1",
        **meta,
    }
    return asyncio.run(
        store.put(USER, StoredResult("device_command", DataClass.CONTENT, text=text, meta=full))
    )


def _compare(store: ResultStore, genie: Any, before: str, after: str, **args: Any) -> ToolOutput:
    extras: dict[str, Any] = {RESULT_STORE_KEY: store}
    if genie is not None:
        extras[GENIE_PARSER_KEY] = genie
    ctx = ToolContext(
        user_id=USER,
        redactor=Redactor(),
        extras=extras,
        sharing=SharingPolicy(inventory=True, addresses=True, content=True),
    )
    tool = build_bgp_learn_tools()[1]
    assert tool.name == "compare_bgp_learns"
    return asyncio.run(tool.handler(ctx, tool.input_model(before=before, after=after, **args)))


UP = {SUMMARY_CMD: _summary("1"), NEIGHBORS_CMD: _neighbors()}
FLAPPED = {
    SUMMARY_CMD: _summary("Active", "never"),
    NEIGHBORS_CMD: _neighbors(dropped=1, reason="Peer closed the session"),
}


def test_compare_reports_a_session_that_went_down_and_flapped(store) -> None:
    genie = TaggedGenie({"a": UP, "b": FLAPPED})
    out = _compare(store, genie, _tagged_run(store, "a"), _tagged_run(store, "b"))

    assert not out.is_error
    body = json.loads(out.content)
    assert body["identical"] is False and "model_diff" not in body
    changed = {r["field"]: (r["before"], r["after"]) for r in body["rows"]}
    assert changed["state"] == ("Established", "Active")
    assert changed["times_dropped"] == (0, 1)
    assert changed["reset_reason"] == (None, "Peer closed the session")
    assert body["summary"]["state_changes"] == 1
    assert genie.replays == [] and genie.diffs == []  # the model diff is opt-in


def test_compare_of_a_reading_with_only_counter_changes_is_identical(store) -> None:
    later = {SUMMARY_CMD: _summary("1", "05:00:00"), NEIGHBORS_CMD: _neighbors()}
    out = _compare(
        store, TaggedGenie({"a": UP, "b": later}), _tagged_run(store, "a"), _tagged_run(store, "b")
    )

    body = json.loads(out.content)
    assert body["identical"] is True and body["rows"] == []


def test_compare_follows_parsed_handles_back_to_the_raw_readings(store) -> None:
    raw_a, raw_b = _tagged_run(store, "a"), _tagged_run(store, "b")
    parsed = asyncio.run(
        store.put(
            USER,
            StoredResult(
                "parsed_output", DataClass.CONTENT, rows=[{"a": 1}], meta={"source_handle": raw_a}
            ),
        )
    )

    out = _compare(store, TaggedGenie({"a": UP, "b": FLAPPED}), parsed, raw_b)

    assert not out.is_error and json.loads(out.content)["identical"] is False


def test_compare_refuses_other_devices_other_scopes_and_the_same_run(store) -> None:
    genie = TaggedGenie({"a": UP, "b": UP})
    a = _tagged_run(store, "a")
    other_device = _tagged_run(store, "b", device_id="dev-2")
    no_device = _tagged_run(store, "b", device_id=None)
    other_scope = _tagged_run(store, "b", commands=[SUMMARY_CMD, NEIGHBORS_CMD])

    assert "same device" in _compare(store, genie, a, other_device).content
    assert "not recorded" in _compare(store, genie, a, no_device).content
    assert "same commands" in _compare(store, genie, a, other_scope).content
    assert "same reading" in _compare(store, genie, a, a).content
    assert all(
        _compare(store, genie, a, h).is_error for h in (other_device, no_device, other_scope, a)
    )


def test_compare_needs_genie_for_both_readings(store) -> None:
    a, b = _tagged_run(store, "a"), _tagged_run(store, "b", parser="textfsm")

    assert _compare(store, None, a, a).is_error
    assert _compare(store, TaggedGenie({"a": UP, "b": UP}), a, b).is_error


def test_compare_refuses_when_a_command_did_not_parse(store) -> None:
    genie = TaggedGenie({"a": UP, "b": {SUMMARY_CMD: _summary("1")}})  # neighbors missing in b
    out = _compare(store, genie, _tagged_run(store, "a"), _tagged_run(store, "b"))

    assert out.is_error and "false changes" in out.content


def test_compare_with_detail_adds_the_learned_model_diff(store) -> None:
    genie = TaggedGenie({"a": UP, "b": FLAPPED})
    out = _compare(store, genie, _tagged_run(store, "a"), _tagged_run(store, "b"), detail=True)

    model = json.loads(out.content)["model_diff"]
    assert model["available"] is True and model["identical"] is False
    assert model["diff"].startswith("-tag")
    assert sorted(genie.replays) == ["a", "b"]
    assert genie.diffs == [list(bgp_compare.MODEL_NOISE_KEYS)]


def test_compare_with_detail_degrades_when_the_replay_fails(store) -> None:
    genie = TaggedGenie({"a": UP, "b": FLAPPED}, replay_error=True)
    out = _compare(store, genie, _tagged_run(store, "a"), _tagged_run(store, "b"), detail=True)

    body = json.loads(out.content)
    assert not out.is_error and body["rows"]  # the record comparison is still there
    assert body["model_diff"] == {
        "available": False,
        "reason": "The pyATS service could not parse the output",
    }


def test_a_reused_device_name_is_not_the_same_device(store) -> None:
    genie = TaggedGenie({"a": UP, "b": UP})
    a = _tagged_run(store, "a")
    same_name_other_id = _tagged_run(store, "b", device_name="LAB", device_id="dev-9")
    other_source = _tagged_run(store, "b", source_id="nb2")

    assert "same device" in _compare(store, genie, a, same_name_other_id).content
    assert "same device" in _compare(store, genie, a, other_source).content


def _cut_run(store: ResultStore, tag: str, *, filled: int) -> str:
    """A run whose stored text was cut: only the first ``filled`` commands have output."""
    outputs = [(c, f"{tag}: {c}" if i < filled else "") for i, c in enumerate(COMMANDS)]
    text, _, spans = _shape_blocks(outputs, lambda v: v)
    meta = {
        "commands": COMMANDS,
        "spans": spans,
        "parser": "genie",
        "network_driver": "cisco_ios",
        "platform": "cisco_ios",
        "device_name": "LAB",
        "device_id": "dev-1",
        "source_id": "nb1",
    }
    return asyncio.run(
        store.put(
            USER,
            StoredResult("device_command", DataClass.CONTENT, text=text, meta=meta, partial=True),
        )
    )


def test_a_cut_in_the_bgp_table_still_compares(store) -> None:
    genie = TaggedGenie({"a": UP, "b": FLAPPED})
    # summary, neighbors and cluster-ids have output; only the last command (the table) was cut.
    out = _compare(store, genie, _cut_run(store, "a", filled=3), _cut_run(store, "b", filled=3))

    assert not out.is_error and json.loads(out.content)["rows"]


def test_a_cut_that_reaches_the_neighbors_is_refused_not_reported_as_removals(store) -> None:
    genie = TaggedGenie({"a": UP, "b": UP})
    whole = _tagged_run(store, "a")

    for filled in (0, 1, 2):  # nothing, only the summary, up to the neighbors command
        out = _compare(store, genie, whole, _cut_run(store, "b", filled=filled))
        assert out.is_error and "cut" in out.content


def test_the_model_diff_is_redacted_as_text_before_it_is_encoded(store) -> None:
    class Secretive(TaggedGenie):
        async def diff_models(self, before, after, exclude):
            return {"identical": False, "diff": " router bgp 65000\n  password 7 0822455D0A16\n+x"}

    genie = Secretive({"a": UP, "b": FLAPPED})
    out = _compare(store, genie, _tagged_run(store, "a"), _tagged_run(store, "b"), detail=True)

    assert "0822455D0A16" not in out.content
    assert json.loads(out.content)["model_diff"]["available"] is True


def test_a_model_diff_too_large_to_redact_is_dropped_not_passed_on(store) -> None:
    from services.ai_assistant.redaction import RedactionBudgetExceeded

    class Boom(Redactor):
        def redact(self, text: str) -> str:
            if "tag" in text:
                raise RedactionBudgetExceeded("too much")
            return super().redact(text)

    ctx_genie = TaggedGenie({"a": UP, "b": FLAPPED})
    extras: dict[str, Any] = {RESULT_STORE_KEY: store, GENIE_PARSER_KEY: ctx_genie}
    ctx = ToolContext(
        user_id=USER,
        redactor=Boom(),
        extras=extras,
        sharing=SharingPolicy(inventory=True, addresses=True, content=True),
    )
    tool = build_bgp_learn_tools()[1]
    args = tool.input_model(
        before=_tagged_run(store, "a"), after=_tagged_run(store, "b"), detail=True
    )

    out = asyncio.run(tool.handler(ctx, args))

    model = json.loads(out.content)["model_diff"]
    assert model["available"] is False and "tag" not in model.get("diff", "")
