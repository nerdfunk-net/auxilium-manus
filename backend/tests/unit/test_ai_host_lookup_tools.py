"""``find_host``: one answer from the stored client data and the APIC's live endpoint table."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import patch

import pytest

from services.aci.common.exceptions import AciAPIError
from services.ai_assistant.client_data_reader import ClientDataAccessError
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools.aci_tools import ACI_READER_KEY
from services.ai_assistant.tools.base import Toolbox, ToolContext, ToolOutput
from services.ai_assistant.tools.client_data_tools import CLIENT_DATA_READER_KEY
from services.ai_assistant.tools.host_lookup_tools import build_host_lookup_tools
from services.ai_assistant.tools.playbook_tools import known_general_tool_names
from tests.unit.test_ai_aci_lookup_tools import (
    EP,
    FakeEndpoints,
    _source,
)
from tests.unit.test_ai_aci_lookup_tools import (
    Reader as AciReader,
)
from tests.unit.test_ai_client_data_tools import ROWS
from tests.unit.test_ai_client_data_tools import FakeReader as ClientReader

ALL = SharingPolicy(inventory=True, addresses=True, content=True)
INVENTORY_ONLY = SharingPolicy(inventory=True)


def _call(
    client: ClientReader,
    aci: AciReader,
    sharing: SharingPolicy = ALL,
    **args: Any,
) -> ToolOutput:
    ctx = ToolContext(
        user_id=1,
        redactor=Redactor(),
        extras={CLIENT_DATA_READER_KEY: client, ACI_READER_KEY: aci},
        sharing=sharing,
    )
    box = Toolbox(build_host_lookup_tools(), ctx)
    return asyncio.run(box.execute(ToolCall(id="1", name="find_host", input=args)))


def _json(out: ToolOutput) -> dict[str, Any]:
    assert not out.is_error, out.content
    return json.loads(out.content)


def test_the_tool_is_one_read_named_find_host() -> None:
    assert [t.name for t in build_host_lookup_tools()] == ["find_host"]


def test_a_mac_is_looked_up_in_both_sources_with_separate_sections() -> None:
    client, aci = ClientReader(), AciReader(_source())

    data = _json(_call(client, aci, address="aabb.ccdd.0001"))

    assert data["client_data"]["status"] == "found"
    assert data["client_data"]["result"]["likely_location"]["device"] == "swB"
    assert data["aci"]["status"] == "found"
    assert data["aci"]["result"]["endpoints"][0]["epg"] == "Web"
    # Each source keeps its own kind of freshness; they are not merged into one age.
    assert "stored" in data["client_data"]["freshness"]
    assert "live" in data["aci"]["freshness"]
    assert data["client_data"]["source"] == "client_data" and data["aci"]["source"] == "aci"


def test_an_ipv4_address_is_looked_up_in_both_sources() -> None:
    client, aci = ClientReader(), AciReader(_source())

    data = _json(_call(client, aci, address="10.193.101.4"))

    assert client.calls[0][1]["ip_address"] == "10.193.101.4"
    assert data["aci"]["status"] == "found"


@pytest.mark.parametrize("address", ["2001:db8::5", "host1.example.net"])
def test_ipv6_and_hostnames_are_client_data_only(address: str) -> None:
    aci_endpoints = FakeEndpoints()
    client, aci = ClientReader(), AciReader(_source(endpoints=aci_endpoints))

    data = _json(_call(client, aci, address=address))

    assert data["aci"]["status"] == "not_applicable"
    assert "IPv4 or a MAC" in data["aci"]["message"]
    assert aci_endpoints.calls == []  # not asked
    assert data["client_data"]["status"] == "found"


def test_not_seen_in_either_source_is_two_answers_with_the_caveats() -> None:
    client = ClientReader(rows=[])
    aci = AciReader(_source(endpoints=FakeEndpoints(())))

    data = _json(_call(client, aci, address="aabb.ccdd.0001"))

    assert data["client_data"]["status"] == "not_seen"
    assert data["aci"]["status"] == "not_learned"
    assert "does not prove" in data["aci"]["result"]["message"]
    assert "get_client_data_coverage" in data["client_data"]["result"]["note"]


def test_one_source_failing_does_not_hide_the_other() -> None:
    client = ClientReader(error=ClientDataAccessError())
    aci = AciReader(_source())

    data = _json(_call(client, aci, address="aabb.ccdd.0001"))

    assert data["client_data"]["status"] == "error"
    assert "client_data:read" in data["client_data"]["message"]
    assert data["aci"]["status"] == "found"


def test_an_aci_failure_is_a_fixed_sentence_next_to_the_client_data() -> None:
    client = ClientReader()
    aci = AciReader(_source(endpoints=FakeEndpoints(error=AciAPIError("boom 10.9.9.9"))))

    data = _json(_call(client, aci, address="aabb.ccdd.0001"))

    assert data["aci"]["status"] == "error"
    assert data["client_data"]["status"] == "found"


def test_both_sources_failing_is_an_error_result() -> None:
    client = ClientReader(error=ClientDataAccessError())
    aci = AciReader(_source(endpoints=FakeEndpoints(error=AciAPIError("x"))))

    out = _call(client, aci, address="aabb.ccdd.0001")

    assert out.is_error
    assert json.loads(out.content)["client_data"]["status"] == "error"


@pytest.mark.parametrize("sharing", [SharingPolicy(), INVENTORY_ONLY])
def test_the_data_switches_gate_the_whole_call_before_any_read(sharing: SharingPolicy) -> None:
    client, aci = ClientReader(), AciReader(_source())

    out = _call(client, aci, sharing, address="aabb.ccdd.0001")

    data = json.loads(out.content)
    # The marker is the whole answer: a withheld source must never read as "not seen".
    assert data["not_shared"] == ("inventory_data" if not sharing.inventory else "device_addresses")
    assert "client_data" not in data and "aci" not in data
    assert out.withheld == (data["not_shared"],)
    assert client.calls == [] and aci.calls == 0


def test_a_value_that_is_nothing_is_a_readable_error_without_a_read() -> None:
    client, aci = ClientReader(), AciReader(_source())

    out = _call(client, aci, address="10.0.0.999")

    assert out.is_error
    assert client.calls == [] and aci.calls == 0


def test_the_answer_is_cut_to_a_few_rows_per_source_and_says_so() -> None:
    many = [{**ROWS[0], "device_name": f"sw{n:02d}", "likely_location": False} for n in range(30)]
    client = ClientReader(rows=many, total=30)
    endpoints = tuple(EP.model_copy(update={"mac": f"45:CD:BB:C0:00:{n:02X}"}) for n in range(12))
    aci = AciReader(_source(endpoints=FakeEndpoints(endpoints)))

    data = _json(_call(client, aci, address="10.193.101.4"))

    assert len(data["client_data"]["result"]["rows"]) == 5
    assert data["client_data"]["result"]["total_rows"] == 30
    assert len(data["aci"]["result"]["endpoints"]) == 5
    assert data["aci"]["result"]["endpoints_total"] == 12
    assert "find_client" in data["note"] and "find_aci_endpoint" in data["note"]


def test_both_sources_run_even_when_the_first_is_slow() -> None:
    order: list[str] = []

    class SlowClient(ClientReader):
        async def observations(self, **filters: Any):
            order.append("client-start")
            await asyncio.sleep(0.05)
            order.append("client-end")
            return await super().observations(**filters)

    class RecordingEndpoints(FakeEndpoints):
        async def find(self, address: str):
            order.append("aci")
            return await super().find(address)

    _json(
        _call(
            SlowClient(),
            AciReader(_source(endpoints=RecordingEndpoints())),
            address="aabb.ccdd.0001",
        )
    )

    assert order.index("aci") < order.index("client-end")  # concurrent, not one after the other


def test_the_aci_budget_is_spent_once_per_call() -> None:
    with patch(
        "services.ai_assistant.tools.aci_tools._within_budget", return_value=False
    ) as budget:
        data = _json(_call(ClientReader(), AciReader(_source()), address="aabb.ccdd.0001"))

    budget.assert_awaited_once()
    assert data["aci"]["status"] == "error"
    assert data["client_data"]["status"] == "found"


# -- wiring -------------------------------------------------------------------------------------


def _surface(**readers: Any) -> tuple[list[str], str]:
    from tests.unit.test_ai_client_data_tools import _general_names

    return _general_names(**readers)


def test_find_host_is_offered_only_when_both_readers_exist() -> None:
    both, system = _surface(client_data_reader=ClientReader(), aci_reader=AciReader(_source()))
    only_client, _ = _surface(client_data_reader=ClientReader())
    only_aci, _ = _surface(aci_reader=AciReader(_source()))
    neither, _ = _surface()

    assert "find_host" in both
    assert "find_host" in system
    assert "find_host" not in only_client
    assert "find_host" not in only_aci
    assert "find_host" not in neither


def test_the_other_tools_are_still_offered_next_to_find_host() -> None:
    both, _ = _surface(client_data_reader=ClientReader(), aci_reader=AciReader(_source()))

    assert {"find_client", "find_aci_endpoint", "find_host"} <= set(both)


def test_playbooks_may_name_find_host() -> None:
    assert "find_host" in known_general_tool_names()


def test_the_prompt_only_mentions_find_host_when_it_is_offered() -> None:
    with_aci = _surface(client_data_reader=ClientReader(), aci_reader=AciReader(_source()))[1]
    without_aci = _surface(client_data_reader=ClientReader())[1]

    assert "find_host" in with_aci
    assert "find_host" not in without_aci


def test_the_source_argument_limits_the_fabric_search_to_that_source() -> None:
    first, second = FakeEndpoints(), FakeEndpoints()
    aci = AciReader(_source("a", endpoints=first), _source("b", endpoints=second))

    _json(_call(ClientReader(), aci, address="aabb.ccdd.0001", source="b"))

    assert first.calls == [] and second.calls == ["aabb.ccdd.0001"]
