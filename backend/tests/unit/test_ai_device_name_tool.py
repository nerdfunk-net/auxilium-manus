"""``get_device_name_matches``: one device name looked up in Batfish and in Nautobot.

Fake readers stand in for both systems; nothing here talks to a network.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest
from nautobot_read.client import Page

from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools.base import Toolbox, ToolContext
from services.ai_assistant.tools.batfish_tools import (
    BATFISH_READER_KEY,
    BatfishAccessError,
    BatfishInputError,
    BatfishUnavailableError,
    NodeListing,
)
from services.ai_assistant.tools.device_name_tools import build_device_name_tools
from services.ai_assistant.tools.nautobot_tools import NAUTOBOT_READER_KEY
from tests.unit.test_ai_nautobot_tools import DEVICE, FakeNautobot, FakeReaderOfContext

FULL = SharingPolicy(inventory=True, addresses=True)


class FakeBatfish:
    def __init__(self) -> None:
        self.sources = ["lab"]
        self.networks = ["net1"]
        self.nodes = ("lab", "r1", "x.a.zz", "x.b.zz")
        self.error: Exception | None = None
        self.calls: list[tuple[Any, ...]] = []

    async def list_sources(self) -> list[str]:
        return self.sources

    async def list_networks(self, source_id: str) -> list[str]:
        return self.networks

    async def node_names(self, source_id: str, network: str, snapshot: str | None) -> NodeListing:
        self.calls.append((source_id, network, snapshot))
        if self.error:
            raise self.error
        return NodeListing(
            snapshot="run-2", snapshot_created="2026-11-01T10:00:00Z", names=self.nodes
        )


class ByNameNautobot(FakeNautobot):
    """Answers a device lookup only for the names it knows (exact filter)."""

    def __init__(self, known: dict[str, dict[str, Any]]) -> None:
        super().__init__()
        self.known = known

    async def list_page(self, root, selection, filters, *, limit, offset):
        self.page_calls.append({"root": root, "filters": dict(filters), "limit": limit})
        if root != "devices":
            return Page(items=tuple(self.rows.get(root, [])), has_more=False)
        (values,) = filters.values()
        found = self.known.get(values[0])
        return Page(items=(found,) if found else (), has_more=False)


def _box(
    batfish: FakeBatfish | None = None,
    nautobot: FakeNautobot | None = None,
    sharing: SharingPolicy = FULL,
    denied: bool = False,
) -> tuple[Toolbox, FakeBatfish, FakeNautobot]:
    batfish = batfish or FakeBatfish()
    nautobot = nautobot or FakeNautobot()
    ctx = ToolContext(
        user_id=1,
        redactor=Redactor(),
        extras={
            BATFISH_READER_KEY: batfish,
            NAUTOBOT_READER_KEY: FakeReaderOfContext(nautobot, denied),
        },
        sharing=sharing,
    )
    return Toolbox(build_device_name_tools(), ctx), batfish, nautobot


def _call(box: Toolbox, **args: Any) -> tuple[Any, Any]:
    out = asyncio.run(box.execute(ToolCall("1", "get_device_name_matches", args)))
    try:
        return out, json.loads(out.content)
    except ValueError:
        return out, None


def test_a_full_name_is_matched_to_the_batfish_node_and_the_nautobot_device() -> None:
    nautobot = ByNameNautobot({"SW-1.local.zz": {**DEVICE, "name": "SW-1.local.zz"}})
    box, batfish, _ = _box(nautobot=nautobot)
    batfish.nodes = ("sw-1", "r1")

    _, data = _call(box, name="SW-1.local.zz")

    assert data["batfish"] == {
        "status": "found",
        "node": "sw-1",
        "network": "net1",
        "snapshot": "run-2",
        "snapshot_created": "2026-11-01T10:00:00Z",
    }
    assert data["nautobot"] == {"status": "found", "name": "SW-1.local.zz"}
    assert batfish.calls == [("lab", "net1", None)]


def test_a_short_batfish_name_is_matched_to_the_nautobot_full_name() -> None:
    nautobot = ByNameNautobot({"lab": {**DEVICE, "name": "LAB.local.zz"}})
    box, _, _ = _box(nautobot=nautobot)

    _, data = _call(box, name="lab")

    assert data["batfish"]["node"] == "lab"
    assert data["nautobot"]["name"] == "LAB.local.zz"


def test_a_device_in_another_domain_is_not_substituted_in_nautobot() -> None:
    """The short Batfish node ``lab`` carries no domain, so it matches ``LAB.other.zz``; Nautobot is
    still asked only with the name given, so it never answers with a different domain's device."""
    nautobot = ByNameNautobot({"lab": {**DEVICE, "name": "LAB.local.zz"}})
    box, _, _ = _box(nautobot=nautobot)

    _, data = _call(box, name="LAB.other.zz")

    assert data["batfish"]["node"] == "lab"
    assert data["nautobot"]["status"] == "not_found"


def test_an_ambiguous_short_name_lists_the_candidates() -> None:
    box, _, _ = _box()

    _, data = _call(box, name="x")

    assert data["batfish"] == {"status": "ambiguous", "candidates": ["x.a.zz", "x.b.zz"]}


def test_an_unknown_name_gets_close_matches() -> None:
    box, _, _ = _box()

    _, data = _call(box, name="r")

    assert data["batfish"]["status"] == "not_found"
    assert "r1" in data["batfish"]["close"]


def test_nautobot_not_found_does_not_hide_the_batfish_answer() -> None:
    nautobot = ByNameNautobot({})
    box, _, _ = _box(nautobot=nautobot)

    _, data = _call(box, name="lab")

    assert data["batfish"]["node"] == "lab"
    assert data["nautobot"]["status"] == "not_found"
    assert "No device 'lab'" in data["nautobot"]["message"]


def test_a_nautobot_name_in_two_domains_is_ambiguous_not_missing() -> None:
    first = {**DEVICE, "name": "lab.a.zz"}
    second = {**DEVICE, "id": "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "name": "lab.b.zz"}

    class TwoMatches(FakeNautobot):
        async def list_page(self, root, selection, filters, *, limit, offset):
            self.page_calls.append({"root": root, "filters": dict(filters), "limit": limit})
            return Page(items=(first, second), has_more=False)

    box, _, _ = _box(nautobot=TwoMatches())

    _, data = _call(box, name="lab")

    assert data["nautobot"]["status"] == "ambiguous"
    assert "lab.a.zz" in data["nautobot"]["message"] and "lab.b.zz" in data["nautobot"]["message"]
    assert data["batfish"]["node"] == "lab"


def test_the_network_is_required_when_several_exist() -> None:
    box, batfish, _ = _box()
    batfish.networks = ["net1", "net2"]

    _, data = _call(box, name="lab")

    assert data["batfish"] == {"status": "network_required", "networks": ["net1", "net2"]}
    assert batfish.calls == []

    _, data = _call(box, name="lab", network="net2", snapshot="run-1")
    assert batfish.calls == [("lab", "net2", "run-1")]


def test_without_the_inventory_opt_in_nothing_is_read() -> None:
    box, batfish, nautobot = _box(sharing=SharingPolicy())

    out, data = _call(box, name="lab")

    assert "not_shared" in json.dumps(data)
    assert batfish.calls == [] and nautobot.requests == 0
    assert not out.is_error


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (BatfishAccessError(), "no_access"),
        (BatfishUnavailableError(), "unavailable"),
    ],
)
def test_batfish_errors_become_a_status_not_a_failed_tool(error, status) -> None:
    box, batfish, _ = _box()
    batfish.error = error

    out, data = _call(box, name="lab")

    assert not out.is_error
    assert data["batfish"]["status"] == status
    assert data["nautobot"]["status"] == "found"


def test_a_batfish_input_error_message_reaches_the_model() -> None:
    box, batfish, _ = _box()
    batfish.error = BatfishInputError("Unknown network 'net1'.")

    _, data = _call(box, name="lab")

    assert data["batfish"] == {"status": "problem", "message": "Unknown network 'net1'."}


def test_without_nautobot_access_that_side_says_so() -> None:
    box, _, _ = _box(denied=True)

    _, data = _call(box, name="lab")

    assert data["nautobot"]["status"] == "no_access"
    assert data["batfish"]["node"] == "lab"


def test_several_or_no_sources_need_a_choice() -> None:
    box, batfish, _ = _box()
    batfish.sources = ["a", "b"]

    _, data = _call(box, name="lab")
    assert data["batfish"] == {"status": "source_required", "sources": ["a", "b"]}

    batfish.sources = []
    _, data = _call(box, name="lab")
    assert data["batfish"]["status"] == "no_source"


@pytest.mark.parametrize(
    "bad", [{"name": ""}, {"name": "a b"}, {"name": "x" * 300}, {"name": "x", "other": 1}]
)
def test_input_is_bounded(bad) -> None:
    box, batfish, nautobot = _box()

    out, _ = _call(box, **bad)

    assert out.is_error
    assert batfish.calls == [] and nautobot.requests == 0


def test_the_tool_name_follows_the_read_rule() -> None:
    names = {t.name for t in build_device_name_tools()}

    assert names == {"get_device_name_matches"}
