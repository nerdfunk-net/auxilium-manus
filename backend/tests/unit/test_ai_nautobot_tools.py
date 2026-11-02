"""Nautobot DCIM / IPAM tools for Ask the Net: gates per data class, errors, redaction, wiring."""

from __future__ import annotations

import asyncio
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from nautobot_read.client import Count, Page
from nautobot_read.client import NautobotError as QueryError
from nautobot_read.context import QueryContext
from nautobot_read.vocabularies import VocabularyCache

from services.ai_assistant import nautobot_query_reader as reader_module
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.nautobot_query_reader import (
    DbNautobotQueryReader,
    NautobotAccessError,
    vocabularies_for,
)
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore
from services.ai_assistant.surfaces import build_general_session
from services.ai_assistant.tools.base import Toolbox, ToolContext
from services.ai_assistant.tools.nautobot_tools import (
    NAUTOBOT_READER_KEY,
    build_nautobot_tools,
)
from services.nautobot.common.exceptions import (
    NautobotAPIError,
    NautobotValidationError,
)
from services.nautobot.credentials import NautobotCredentials
from services.nautobot.graphql_client import NautobotServiceClient, failure_message
from tests.unit.test_ai_batfish_tools import FakeReader

UUID_DE = "11111111-1111-1111-1111-111111111111"
UUID_BER = "22222222-2222-2222-2222-222222222222"
UUID_DEV = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
SECRET = "hunter2hunter2"

LOCATIONS = [
    {"id": UUID_DE, "name": "Germany", "description": "Country HQ", "parent": None,
     "location_type": {"name": "Country"}, "status": {"name": "Active"}, "tags": []},
    {"id": UUID_BER, "name": "Berlin", "description": "",
     "parent": {"id": UUID_DE, "name": "Germany"},
     "location_type": {"name": "City"}, "status": {"name": "Active"}, "tags": []},
]
DEVICE = {
    "id": UUID_DEV, "name": "sw-1", "serial": "SN-1", "role": {"name": "Network"},
    "status": {"name": "Active"},
    "device_type": {"model": "c9300", "manufacturer": {"name": "Cisco"}},
    "platform": {"name": "Cisco IOS"}, "location": {"id": UUID_BER, "name": "Berlin"},
    "primary_ip4": {"address": "10.0.0.1/24"}, "tags": [],
}
DEVICE_DETAIL = {
    **DEVICE, "asset_tag": "AT-1", "comments": "free text", "rack": {"name": "R1"},
    "tenant": None, "primary_ip6": None,
}
INTERFACES = [
    {"name": "Gi1", "type": "1000base-t", "enabled": True, "mac_address": None,
     "description": "uplink", "status": {"name": "Active"},
     "ip_addresses": [{"address": "10.0.0.1/24"}]},
]
IP_ROW = {
    "id": "cc", "address": "10.0.0.1/24", "dns_name": "", "type": "HOST", "description": "",
    "status": {"name": "Active"}, "role": None,
    "parent": {"prefix": "10.0.0.0/24", "namespace": {"name": "Global"}}, "tenant": None,
    "tags": [], "interfaces": [{"name": "Gi1", "device": {"name": "sw-1"}}], "primary_ip4_for": [],
}
UUID_PFX = "dddddddd-dddd-dddd-dddd-dddddddddddd"
PREFIX_ROW = {"id": UUID_PFX, "prefix": "10.0.0.0/24", "namespace": {"name": "Global"}}
UUID_VC = "99999999-9999-9999-9999-999999999999"
STACK = {
    "id": UUID_VC, "name": "LAB.local.zz",
    "members": [
        {"id": UUID_DEV, "name": "LAB.local.zz", "serial": "SN-1", "vc_position": 1,
         "vc_priority": 15, "device_type": {"model": "C9300"}, "platform": None,
         "primary_ip4": {"address": "10.0.0.1/24"},
         "vc_master_for": {"id": UUID_VC, "name": "LAB.local.zz"}},
        {"id": "bb", "name": "LAB:2.local.zz", "serial": "SN-2", "vc_position": 2,
         "vc_priority": 1, "device_type": {"model": "C9300"}, "platform": None,
         "primary_ip4": None, "vc_master_for": None},
    ],
}
VOCAB = {
    "virtual_chassis": [{"name": "LAB.local.zz"}],
    "roles": [{"name": "Network"}, {"name": "Server"}],
    "statuses": [{"name": "Active"}],
    "tags": [],
    "device_types": [{"model": "c9300", "manufacturer": {"name": "Cisco"}}],
    "platforms": [{"name": "Cisco IOS", "manufacturer": None, "network_driver": "cisco_ios"}],
    "namespaces": [{"name": "Global"}],
    "location_types": [{"name": "Country", "nestable": False, "parent": None}],
}


class FakeNautobot:
    """Canned Nautobot that records every request, so a test can assert nothing was sent."""

    def __init__(self) -> None:
        self.page_calls: list[dict[str, Any]] = []
        self.graphql_calls = 0
        self.rest_calls: list[str] = []
        self.has_more = False
        self.count_calls: list[tuple[str, dict[str, Any]]] = []
        self.available: Any = [{"address": f"10.0.0.{n}/24"} for n in range(0, 12)]
        self.rows: dict[str, list[dict[str, Any]]] = {
            "devices": [DEVICE], "interfaces": INTERFACES, "ip_addresses": [IP_ROW],
            "prefixes": [PREFIX_ROW], "locations": LOCATIONS, "virtual_chassis": [STACK],
        }

    @property
    def requests(self) -> int:
        return (
            len(self.page_calls) + self.graphql_calls + len(self.rest_calls) + len(self.count_calls)
        )

    async def list_all(self, root, selection, filters=None, **_):
        return LOCATIONS if root == "locations" else VOCAB[root]

    async def list_page(self, root, selection, filters, *, limit, offset):
        self.page_calls.append({"root": root, "filters": dict(filters), "limit": limit})
        return Page(items=tuple(self.rows.get(root, [])), has_more=self.has_more)

    async def count(self, root, filters):
        self.count_calls.append((root, dict(filters)))
        return Count(137, exact=True)

    async def rest_get(self, endpoint):
        self.rest_calls.append(endpoint)
        return self.available

    async def graphql(self, query, variables=None):
        self.graphql_calls += 1
        return {"device": DEVICE_DETAIL, "location": LOCATIONS[1]}


class FakeReaderOfContext:
    def __init__(self, nautobot: FakeNautobot, denied: bool = False) -> None:
        self.nautobot = nautobot
        self.denied = denied

    async def context(self) -> QueryContext:
        if self.denied:
            raise NautobotAccessError
        return QueryContext(
            client=self.nautobot, vocabularies=VocabularyCache(self.nautobot)
        )


def _toolbox(
    nautobot: FakeNautobot | None = None,
    *,
    sharing: SharingPolicy = SharingPolicy(),
    denied: bool = False,
    redactor: Redactor | None = None,
) -> tuple[Toolbox, FakeNautobot]:
    nautobot = nautobot or FakeNautobot()
    context = ToolContext(
        user_id=1,
        redactor=redactor or Redactor(),
        extras={NAUTOBOT_READER_KEY: FakeReaderOfContext(nautobot, denied)},
        sharing=sharing,
    )
    return Toolbox(build_nautobot_tools(), context), nautobot


def _call(box: Toolbox, name: str, **input_: Any):
    return asyncio.run(box.execute(ToolCall("1", name, input_)))


def _data(output) -> dict[str, Any]:
    assert not output.is_error, output.content
    return json.loads(output.content)


FULL = SharingPolicy(inventory=True, addresses=True)
BASIC = SharingPolicy(inventory=True)


# -- the tool set ----------------------------------------------------------------------------


def test_the_tool_set_is_reads_only_with_the_names_the_library_errors_point_to() -> None:
    names = {t.name for t in build_nautobot_tools()}

    assert names == {
        "list_locations", "get_location", "list_location_types", "list_roles", "list_statuses",
        "list_tags", "list_devices", "get_device", "list_device_types", "list_platforms",
        "list_ip_addresses", "list_prefixes", "list_namespaces", "get_next_free_ip",
        "list_interfaces", "list_virtual_chassis", "get_virtual_chassis",
    }
    assert all(n.startswith(("get_", "list_")) for n in names)


def test_inputs_reject_unknown_fields_empty_names_and_oversized_pages() -> None:
    box, nautobot = _toolbox(sharing=FULL)

    for bad in ({"colour": "red"}, {"role": ""}, {"limit": 101}, {"limit": 0}, {"offset": -1}):
        out = _call(box, "list_devices", **bad)
        assert out.is_error and "Invalid input for list_devices" in out.content
    assert nautobot.requests == 0


# -- data sharing: devices -------------------------------------------------------------------


def test_devices_without_the_inventory_switch_answer_with_the_marker_and_send_nothing() -> None:
    box, nautobot = _toolbox(sharing=SharingPolicy())

    for name, args in (("list_devices", {}), ("get_device", {"device": "sw-1"})):
        assert _data(_call(box, name, **args))["not_shared"] == "inventory_data"
    assert nautobot.requests == 0


def test_devices_with_only_the_inventory_switch_leave_out_addresses_and_say_why() -> None:
    box, _ = _toolbox(sharing=BASIC)

    data = _data(_call(box, "list_devices", role="network"))

    item = data["items"][0]
    assert (item["name"], item["role"]) == ("sw-1", "Network")
    assert item["location"] == "Germany → Berlin"
    assert "primary_ip4" not in item and "serial" not in item
    assert data["withheld_fields"] == {
        "primary_ip4": "device_addresses", "serial": "device_addresses",
    }
    assert "10.0.0.1" not in json.dumps(data) and "SN-1" not in json.dumps(data)


def test_devices_with_the_addresses_switch_include_them() -> None:
    box, _ = _toolbox(sharing=FULL)

    data = _data(_call(box, "list_devices"))

    assert data["items"][0]["primary_ip4"] == "10.0.0.1/24"
    assert data["items"][0]["serial"] == "SN-1"
    assert "withheld_fields" not in data


def test_get_device_withholds_interfaces_without_addresses_and_never_shows_comments() -> None:
    box, _ = _toolbox(sharing=BASIC)

    data = _data(_call(box, "get_device", device=UUID_DEV))

    assert data["name"] == "sw-1" and data["rack"] == "R1"
    assert "interfaces" not in data and "asset_tag" not in data
    assert data["withheld_fields"]["interfaces"] == "device_addresses"
    assert data["withheld_fields"]["comments"] == "never"
    assert "free text" not in json.dumps(data)


def test_get_device_with_addresses_includes_interfaces_but_still_not_comments() -> None:
    box, _ = _toolbox(sharing=FULL)

    data = _data(_call(box, "get_device", device=UUID_DEV))

    assert data["interfaces"][0]["ip_addresses"] == ["10.0.0.1/24"]
    assert data["asset_tag"] == "AT-1"
    # The interface text is free text: withheld without the content opt-in, like comments.
    assert data["withheld_fields"] == {
        "comments": "never", "interface_descriptions": "content_data",
    }
    assert "description" not in data["interfaces"][0]


def test_a_field_no_rule_names_is_never_sent() -> None:
    box, _ = _toolbox(sharing=FULL)
    with patch("nautobot_read.queries.dcim.device_item") as shaped:
        shaped.return_value = {"id": "x", "name": "sw-1", "surprise": "value"}
        data = _data(_call(box, "list_devices"))

    assert "surprise" not in data["items"][0]
    assert data["withheld_fields"] == {"surprise": "never"}


# -- data sharing: locations, IPAM, vocabulary -----------------------------------------------


def test_locations_are_available_without_any_switch_but_details_need_inventory() -> None:
    box, _ = _toolbox(sharing=SharingPolicy())

    listed = _data(_call(box, "list_locations"))
    one = _data(_call(box, "get_location", location="Germany → Berlin"))

    assert [i["path"] for i in listed["items"]] == ["Germany", "Germany → Berlin"]
    assert "description" not in listed["items"][0]
    assert listed["withheld_fields"]["description"] == "inventory_data"
    assert one["path"] == "Germany → Berlin" and "latitude" not in one
    assert "Country HQ" not in json.dumps([listed, one])

    shared = _data(_call(_toolbox(sharing=BASIC)[0], "list_locations"))
    assert shared["items"][0]["description"] == "Country HQ"


def test_ipam_needs_the_addresses_switch_and_sends_nothing_without_it() -> None:
    for sharing in (SharingPolicy(), BASIC):
        box, nautobot = _toolbox(sharing=sharing)
        for name, args in (
            ("list_ip_addresses", {}),
            ("list_prefixes", {}),
            ("get_next_free_ip", {"prefix": "10.0.0.0/24"}),
        ):
            assert _data(_call(box, name, **args))["not_shared"] == "device_addresses"
        assert nautobot.requests == 0


def test_ipam_with_the_addresses_switch_returns_the_rows() -> None:
    box, nautobot = _toolbox(sharing=FULL)

    data = _data(_call(box, "list_ip_addresses", prefix="10.0.0.7/24", device=UUID_DEV))

    assert data["items"][0]["assigned_to"] == [{"device": "sw-1", "interface": "Gi1"}]
    ip_call = next(c for c in nautobot.page_calls if c["root"] == "ip_addresses")
    assert ip_call["filters"]["prefix"] == ["10.0.0.0/24"]


# -- interfaces of a device with many of them ---------------------------------------------------


def test_list_interfaces_needs_the_addresses_switch_and_sends_nothing_without_it() -> None:
    for sharing in (SharingPolicy(), BASIC):
        box, nautobot = _toolbox(sharing=sharing)

        out = _data(_call(box, "list_interfaces", device="sw-1"))

        assert out["not_shared"] == "device_addresses"
        assert nautobot.requests == 0


def test_list_interfaces_pages_and_filters_the_device_interfaces() -> None:
    box, nautobot = _toolbox(sharing=FULL)

    data = _data(
        _call(box, "list_interfaces", device=UUID_DEV, name_contains="Gi", limit=30, offset=60)
    )

    call = next(c for c in nautobot.page_calls if c["root"] == "interfaces")
    assert call["filters"] == {"device_id": [UUID_DEV], "name__ic": ["Gi"]}
    assert call["limit"] == 30
    assert data["items"][0]["name"] == "Gi1"
    assert data["offset"] == 60 and data["has_more"] is False


def test_list_interfaces_inputs_are_bounded() -> None:
    box, nautobot = _toolbox(sharing=FULL)

    for bad in (
        {"device": "sw-1", "limit": 51},
        {"device": "sw-1", "limit": 0},
        {"device": "sw-1", "offset": -1},
        {"device": ""},
        {"device": "sw-1", "other": 1},
        {},
    ):
        out = _call(box, "list_interfaces", **bad)
        assert out.is_error and "Invalid input for list_interfaces" in out.content
    assert nautobot.requests == 0


CONTENT_TOO = SharingPolicy(inventory=True, addresses=True, content=True)


def test_interface_descriptions_need_the_content_opt_in_in_both_tools() -> None:
    without, _ = _toolbox(sharing=FULL)
    with_content, _ = _toolbox(sharing=CONTENT_TOO)

    listed = _data(_call(without, "list_interfaces", device=UUID_DEV))
    assert "description" not in listed["items"][0]
    assert listed["withheld_fields"] == {"interface_descriptions": "content_data"}
    assert listed["items"][0]["name"] == "Gi1"

    shown = _data(_call(with_content, "list_interfaces", device=UUID_DEV))
    assert shown["items"][0]["description"] == "uplink"
    assert "withheld_fields" not in shown

    device = _data(_call(with_content, "get_device", device=UUID_DEV))
    assert device["interfaces"][0]["description"] == "uplink"


def test_get_device_points_to_list_interfaces_for_the_rest() -> None:
    spec = next(t for t in build_nautobot_tools() if t.name == "get_device")

    assert "list_interfaces" in spec.description


@pytest.mark.parametrize(
    ("name", "args", "expected"),
    [
        ("list_roles", {}, ["Network", "Server"]),
        ("list_statuses", {"content_type": "ipam.prefix"}, ["Active"]),
        ("list_namespaces", {}, ["Global"]),
    ],
)
def test_vocabulary_tools_need_no_switch(name, args, expected) -> None:
    box, _ = _toolbox(sharing=SharingPolicy())

    data = _data(_call(box, name, **args))

    assert [i["name"] for i in data["items"]] == expected


def test_device_types_platforms_location_types_and_tags_need_no_switch() -> None:
    box, _ = _toolbox(sharing=SharingPolicy())

    assert _data(_call(box, "list_device_types"))["items"][0]["model"] == "c9300"
    assert _data(_call(box, "list_platforms"))["items"][0]["name"] == "Cisco IOS"
    assert _data(_call(box, "list_location_types"))["items"][0]["name"] == "Country"
    assert _data(_call(box, "list_tags"))["items"] == []


def test_the_child_location_claim_is_limited_to_devices() -> None:
    from services.ai_assistant.prompts import NAUTOBOT_PROMPT

    # Verified for devices(location:); open for prefixes (mcp/nautobot/doc/TODO.md).
    assert "A device location filter includes child locations" in NAUTOBOT_PROMPT
    assert "prefix location filter is not verified" in NAUTOBOT_PROMPT
    assert "A location filter includes child" not in NAUTOBOT_PROMPT
    specs = {t.name: t for t in build_nautobot_tools()}
    schema = specs["list_prefixes"].spec.input_schema["properties"]["location"]
    assert "Not verified" in schema["description"]
    assert "may not include child locations" in specs["list_prefixes"].description


# -- get_next_free_ip ------------------------------------------------------------------------


def test_the_next_free_ip_is_returned_with_the_not_reserved_warning() -> None:
    box, nautobot = _toolbox(sharing=FULL)

    data = _data(_call(box, "get_next_free_ip", prefix="10.0.0.0/24", count=2))

    assert data["addresses"] == ["10.0.0.1", "10.0.0.2"]
    assert (data["prefix"], data["namespace"], data["complete"]) == ("10.0.0.0/24", "Global", True)
    assert "nothing is reserved" in data["note"].lower()
    assert nautobot.rest_calls == [f"ipam/prefixes/{UUID_PFX}/available-ips/?limit=3&format=json"]


def test_the_next_free_ip_input_is_bounded_and_strict() -> None:
    box, nautobot = _toolbox(sharing=FULL)

    for bad in (
        {}, {"prefix": ""}, {"prefix": "10.0.0.0/24", "count": 0},
        {"prefix": "10.0.0.0/24", "count": 21}, {"prefix": "10.0.0.0/24", "start_offset": -1},
        {"prefix": "10.0.0.0/24", "reserve": True},
    ):
        out = _call(box, "get_next_free_ip", **bad)
        assert out.is_error and "Invalid input for get_next_free_ip" in out.content
    assert nautobot.requests == 0


def test_a_prefix_in_two_namespaces_reaches_the_model_as_a_question() -> None:
    nautobot = FakeNautobot()
    nautobot.rows["prefixes"] = [
        PREFIX_ROW, {**PREFIX_ROW, "namespace": {"name": "black"}},
    ]
    box, _ = _toolbox(nautobot, sharing=FULL)

    out = _call(box, "get_next_free_ip", prefix="10.0.0.0/24")

    assert out.is_error and "exists in 2 namespaces: Global, black" in out.content
    assert nautobot.rest_calls == []


def test_next_free_addresses_are_redacted_like_every_other_nautobot_text() -> None:
    redactor = Redactor()
    redactor.add_known_secrets(["10.0.0.1"])
    box, _ = _toolbox(sharing=FULL, redactor=redactor)

    out = _call(box, "get_next_free_ip", prefix="10.0.0.0/24")

    assert '"10.0.0.1"' not in out.content


# -- errors and redaction --------------------------------------------------------------------


def test_an_unknown_name_gives_the_model_the_closest_and_available_names() -> None:
    box, nautobot = _toolbox(sharing=FULL)

    out = _call(box, "list_devices", role="router")

    assert out.is_error
    assert "No dcim.device role 'router'" in out.content
    assert "Available: Network, Server" in out.content
    assert nautobot.page_calls == []


def test_a_user_without_access_gets_a_clear_error() -> None:
    box, _ = _toolbox(sharing=FULL, denied=True)

    out = _call(box, "list_roles")

    assert out.is_error and "cannot read Nautobot data" in out.content


def test_a_failing_nautobot_reaches_the_model_as_the_short_message_only() -> None:
    nautobot = FakeNautobot()

    async def down(*_a, **_k):
        raise QueryError("Could not reach Nautobot. Check that it is running.")

    nautobot.list_page = down  # type: ignore[method-assign]
    box, _ = _toolbox(nautobot, sharing=FULL)

    out = _call(box, "list_devices")

    assert out.is_error and out.content == "Could not reach Nautobot. Check that it is running."


def test_a_bug_is_contained_by_the_choke_point_and_not_shown() -> None:
    nautobot = FakeNautobot()

    async def boom(*_a, **_k):
        raise RuntimeError("secret internal detail")

    nautobot.list_page = boom  # type: ignore[method-assign]
    box, _ = _toolbox(nautobot, sharing=FULL)

    out = _call(box, "list_devices")

    assert out.is_error and "secret internal detail" not in out.content


def test_known_secrets_in_nautobot_text_are_redacted() -> None:
    redactor = Redactor()
    redactor.add_known_secrets([SECRET])
    nautobot = FakeNautobot()
    nautobot.rows["devices"] = [{**DEVICE, "name": f"sw-{SECRET}"}]
    box, _ = _toolbox(nautobot, sharing=FULL, redactor=redactor)

    out = _call(box, "list_devices")

    assert SECRET not in out.content


def test_a_known_secret_with_json_special_characters_is_redacted_before_encoding() -> None:
    # json.dumps escapes the quote and the backslash, so the text pass at the choke point alone
    # would no longer find this secret in the output.
    tricky = 'pa"ss\\word-99'
    redactor = Redactor()
    redactor.add_known_secrets([tricky])
    nautobot = FakeNautobot()
    nautobot.rows["devices"] = [{**DEVICE, "name": f"sw-{tricky}"}]
    box, _ = _toolbox(nautobot, sharing=FULL, redactor=redactor)

    out = _call(box, "list_devices")

    assert "word-99" not in out.content and "sw-" in out.content


def test_long_text_is_capped() -> None:
    nautobot = FakeNautobot()
    nautobot.rows["devices"] = [{**DEVICE, "name": "x" * 900}]
    box, _ = _toolbox(nautobot, sharing=FULL)

    name = _data(_call(box, "list_devices"))["items"][0]["name"]

    assert len(name) == 501 and name.endswith("…")


# -- the transport on top of NautobotService -------------------------------------------------

CREDENTIALS = NautobotCredentials(url="https://nb.example", token="tok")


class _Service:
    def __init__(self, result=None, error=None) -> None:
        self.result, self.error, self.calls = result, error, []

    async def graphql_query(self, query, variables, credentials, *, strict=False):
        self.calls.append((query, variables, credentials, strict))
        if self.error:
            raise self.error
        return self.result


def test_the_transport_asks_strictly_and_unwraps_data() -> None:
    service = _Service({"data": {"devices": []}})

    data = asyncio.run(NautobotServiceClient(service, CREDENTIALS).graphql("{x}", {"a": 1}))

    assert data == {"devices": []}
    assert service.calls == [("{x}", {"a": 1}, CREDENTIALS, True)]


def test_a_caller_may_use_data_next_to_a_graphql_error_and_only_the_count_is_logged(caplog) -> None:
    service = _Service({"data": {"x": 1}, "errors": [{"message": "token=hunter2-from-nautobot"}]})

    with caplog.at_level("WARNING"):
        data = asyncio.run(
            NautobotServiceClient(service, CREDENTIALS, strict=False).graphql("{x}")
        )

    assert data == {"x": 1} and service.calls[0][3] is False
    assert "1 error(s)" in caplog.text and "hunter2" not in caplog.text


@pytest.mark.parametrize("result", [None, {}, {"data": None}, {"data": []}, "text"])
def test_an_unexpected_response_is_an_error(result) -> None:
    with pytest.raises(QueryError, match="unexpected response"):
        asyncio.run(NautobotServiceClient(_Service(result), CREDENTIALS).graphql("{x}"))


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (NautobotAPIError("raw 401 body <html>", http_status=401), "rejected the API token"),
        (NautobotAPIError("raw", http_status=403), "lacks permission"),
        (NautobotAPIError("raw", code="timeout"), "did not answer in time"),
        (NautobotAPIError("raw 10.1.2.3", code="transport"), "Could not reach Nautobot"),
        (NautobotAPIError("raw", code="graphql_error"), "rejected the query"),
        (NautobotAPIError("raw", http_status=502), "HTTP 502"),
        (NautobotValidationError("Unsafe URL http://169.254.169.254"), "not usable"),
    ],
)
def test_failures_become_short_fixed_messages_without_upstream_text(error, expected) -> None:
    with pytest.raises(QueryError) as caught:
        asyncio.run(NautobotServiceClient(_Service(error=error), CREDENTIALS).graphql("{x}"))

    assert expected in str(caught.value)
    for leaked in ("raw", "<html>", "10.1.2.3", "169.254"):
        assert leaked not in str(caught.value)


class _RestService(_Service):
    async def rest_request(self, endpoint, credentials, method="GET", data=None):
        self.calls.append((endpoint, method, data, credentials))
        if self.error:
            raise self.error
        return self.result


def test_rest_get_is_a_get_with_the_given_endpoint_and_returns_the_body_as_is() -> None:
    service = _RestService([{"address": "10.0.0.1/24"}])

    body = asyncio.run(
        NautobotServiceClient(service, CREDENTIALS).rest_get("ipam/prefixes/x/available-ips/")
    )

    assert body == [{"address": "10.0.0.1/24"}]
    assert service.calls == [("ipam/prefixes/x/available-ips/", "GET", None, CREDENTIALS)]


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (NautobotAPIError("raw 401 <html>", http_status=401), "rejected the API token"),
        (NautobotAPIError("not found: ipam/prefixes/secret-id", http_status=404), "HTTP 404"),
        (NautobotAPIError("raw", code="timeout"), "did not answer in time"),
        (NautobotValidationError("Unsafe URL http://169.254.169.254"), "not usable"),
    ],
)
def test_rest_failures_become_short_fixed_messages_without_upstream_text(error, expected) -> None:
    with pytest.raises(QueryError) as caught:
        asyncio.run(NautobotServiceClient(_RestService(error=error), CREDENTIALS).rest_get("x/"))

    assert expected in str(caught.value)
    for leaked in ("raw", "<html>", "secret-id", "169.254"):
        assert leaked not in str(caught.value)


def test_failure_message_has_a_fallback_for_a_bare_error() -> None:
    assert "not usable" in failure_message(NautobotAPIError("x"))


# -- the vocabulary cache --------------------------------------------------------------------


def test_the_vocabulary_cache_is_shared_per_scope_and_bounded() -> None:
    with patch.dict(reader_module._vocabularies, clear=True):
        client = object()
        first = vocabularies_for("a", client)  # type: ignore[arg-type]

        assert vocabularies_for("a", object()) is first  # type: ignore[arg-type]
        for index in range(reader_module.MAX_CACHED_INSTANCES):
            vocabularies_for(f"s{index}", client)  # type: ignore[arg-type]
        assert "a" not in reader_module._vocabularies
        assert len(reader_module._vocabularies) == reader_module.MAX_CACHED_INSTANCES


def test_using_a_scope_keeps_it_from_being_the_one_evicted() -> None:
    with patch.dict(reader_module._vocabularies, clear=True):
        client = object()
        keep = vocabularies_for("keep", client)  # type: ignore[arg-type]
        for index in range(reader_module.MAX_CACHED_INSTANCES - 1):
            vocabularies_for(f"s{index}", client)  # type: ignore[arg-type]
        vocabularies_for("keep", client)  # type: ignore[arg-type]
        vocabularies_for("new", client)  # type: ignore[arg-type]

        assert reader_module._vocabularies["keep"] is keep


# -- the database-backed reader --------------------------------------------------------------


def _summaries(*ids: str):
    return MagicMock(sources=[MagicMock(source_id=i) for i in ids])


def _load(rbac_allows: bool, summaries, credentials):
    rbac = MagicMock()
    rbac.return_value.has_permission.return_value = rbac_allows
    settings = MagicMock()
    settings.return_value.list_nautobot_source_summaries.return_value = summaries
    with (
        patch.object(reader_module, "SessionLocal"),
        patch.object(reader_module, "RBACService", rbac),
        patch.object(reader_module, "SettingsService", settings),
        patch.object(reader_module, "nautobot_credentials_from_source_id", credentials),
    ):
        try:
            return DbNautobotQueryReader(user_id=5)._credentials(), rbac
        except NautobotAccessError:
            return None, rbac


def test_the_reader_checks_the_source_permission_on_every_call() -> None:
    loaded, rbac = _load(False, _summaries("nb"), lambda s, d: CREDENTIALS)

    assert loaded is None
    rbac.return_value.has_permission.assert_called_once_with(5, "sources.nautobot", "read")


def test_the_reader_skips_an_unusable_source_and_binds_to_the_first_usable_one() -> None:
    def credentials(source_id, db):
        if source_id == "bad":
            raise RuntimeError("no url")
        return NautobotCredentials(url=f"https://{source_id}.example", token="t")

    loaded, _ = _load(True, _summaries("bad", "good", "other"), credentials)

    assert loaded.url == "https://good.example"


def test_the_reader_without_a_usable_source_is_denied() -> None:
    def credentials(source_id, db):
        raise RuntimeError("no url")

    assert _load(True, _summaries("bad"), credentials)[0] is None
    assert _load(True, _summaries(), credentials)[0] is None


def test_a_broken_source_is_logged_with_its_error_type_but_not_its_message(caplog) -> None:
    def credentials(source_id, db):
        if source_id == "bad":
            raise KeyError("token=hunter2-from-the-error")
        return CREDENTIALS

    with caplog.at_level("INFO", logger=reader_module.logger.name):
        loaded, _ = _load(True, _summaries("bad", "good"), credentials)

    assert loaded is CREDENTIALS
    warning = next(r for r in caplog.records if "'bad'" in r.getMessage())
    assert warning.levelname == "WARNING" and "KeyError" in warning.getMessage()
    assert "hunter2" not in caplog.text


def test_all_sources_failing_is_logged_apart_from_having_none(caplog) -> None:
    def broken(source_id, db):
        raise RuntimeError("boom")

    with caplog.at_level("INFO", logger=reader_module.logger.name):
        assert _load(True, _summaries("a", "b"), broken)[0] is None
        failed = [r.getMessage() for r in caplog.records]
        caplog.clear()
        assert _load(True, _summaries(), broken)[0] is None
        none_configured = [r.getMessage() for r in caplog.records]

    assert any("none of the 2 Nautobot source(s) is usable" in m for m in failed)
    assert none_configured and all("none of the" not in m for m in none_configured)
    assert any("no Nautobot source is configured" in m for m in none_configured)


def test_context_builds_a_client_and_a_shared_vocabulary_cache() -> None:
    reader = DbNautobotQueryReader(user_id=5)
    service = object()
    with (
        patch.dict(reader_module._vocabularies, clear=True),
        patch.object(reader, "_credentials", return_value=CREDENTIALS),
        patch.object(
            reader_module.service_factory, "get_nautobot_app_service", return_value=service
        ),
    ):
        first = asyncio.run(reader.context())
        second = asyncio.run(reader.context())

    assert isinstance(first.client, NautobotServiceClient)
    assert first.vocabularies is second.vocabularies


# -- the general surface ---------------------------------------------------------------------


def _session(**overrides):
    base = {
        "user_id": 7,
        "reader": FakeReader(),
        "store": ResultStore(InMemoryResultBackend()),
        "sharing": FULL,
        "may_query_batfish": True,
        "nautobot_reader": FakeReaderOfContext(FakeNautobot()),
    }
    base.update(overrides)
    return build_general_session(**base)


def test_the_surface_offers_the_nautobot_tools_next_to_the_batfish_ones() -> None:
    names = {s.name for s in _session().toolbox.specs()}

    assert {"list_devices", "get_device", "list_prefixes", "get_routes"} <= names
    assert "Nautobot:" in _session().system


def test_the_name_matching_tool_needs_both_batfish_and_nautobot() -> None:
    both = {s.name for s in _session().toolbox.specs()}
    only_batfish = {s.name for s in _session(nautobot_reader=None).toolbox.specs()}
    only_nautobot = {s.name for s in _session(may_query_batfish=False).toolbox.specs()}

    assert "get_device_name_matches" in both
    assert "get_device_name_matches" not in only_batfish | only_nautobot


def test_the_surface_without_a_reader_has_no_nautobot_tools_or_prompt() -> None:
    session = _session(nautobot_reader=None)

    assert "list_devices" not in {s.name for s in session.toolbox.specs()}
    assert "Nautobot:" not in session.system


def test_without_the_batfish_permission_the_nautobot_tools_are_still_offered() -> None:
    session = _session(may_query_batfish=False)

    names = {s.name for s in session.toolbox.specs()}

    assert "list_devices" in names and "get_routes" not in names
    assert "only the Nautobot tools" in session.system
    assert session.budget.max_tool_steps > 8


def test_without_any_permission_the_surface_still_has_no_tools() -> None:
    session = _session(may_query_batfish=False, nautobot_reader=None)

    assert not session.toolbox.specs()
    assert "you have no tools" in session.system


def test_the_playbook_tool_list_includes_the_nautobot_tools() -> None:
    session = _session()

    available = session.toolbox._context.extras["available_tools"]

    assert {"list_devices", "get_routes"} <= available


# -- virtual chassis (stacks) ----------------------------------------------------------------


def test_stacks_without_the_inventory_switch_answer_with_the_marker_and_send_nothing() -> None:
    box, nautobot = _toolbox(sharing=SharingPolicy())

    for name, args in (
        ("list_virtual_chassis", {}), ("get_virtual_chassis", {"virtual_chassis": "LAB.local.zz"}),
    ):
        assert _data(_call(box, name, **args))["not_shared"] == "inventory_data"
    assert nautobot.requests == 0


def test_list_stacks_with_only_the_inventory_switch_leaves_out_the_master_address() -> None:
    box, _ = _toolbox(sharing=BASIC)

    data = _data(_call(box, "list_virtual_chassis"))

    item = data["items"][0]
    assert item["name"] == "LAB.local.zz" and item["master"] == "LAB.local.zz"
    assert item["members"] == ["LAB.local.zz", "LAB:2.local.zz"] and item["member_count"] == 2
    assert "master_primary_ip4" not in item
    assert data["withheld_fields"] == {"master_primary_ip4": "device_addresses"}
    assert "10.0.0.1" not in json.dumps(data)


def test_list_stacks_with_addresses_includes_the_master_address() -> None:
    box, _ = _toolbox(sharing=FULL)

    data = _data(_call(box, "list_virtual_chassis", name_contains="lab"))

    assert data["items"][0]["master_primary_ip4"] == "10.0.0.1/24"
    assert "withheld_fields" not in data


def test_get_stack_without_addresses_drops_member_addresses_and_serials() -> None:
    box, _ = _toolbox(sharing=BASIC)

    data = _data(_call(box, "get_virtual_chassis", virtual_chassis="lab.local.zz"))

    assert [m["name"] for m in data["members"]] == ["LAB.local.zz", "LAB:2.local.zz"]
    assert data["members"][0]["is_master"] is True and data["members"][0]["position"] == 1
    assert all("primary_ip4" not in m and "serial" not in m for m in data["members"])
    assert data["withheld_fields"]["primary_ip4"] == "device_addresses"
    assert data["withheld_fields"]["serial"] == "device_addresses"
    assert "SN-1" not in json.dumps(data) and "10.0.0.1" not in json.dumps(data)


def test_get_stack_with_addresses_includes_member_addresses_and_serials() -> None:
    box, _ = _toolbox(sharing=FULL)

    data = _data(_call(box, "get_virtual_chassis", virtual_chassis="LAB.local.zz"))

    assert data["members"][0]["primary_ip4"] == "10.0.0.1/24"
    assert data["members"][1]["serial"] == "SN-2"
    assert "withheld_fields" not in data


def test_get_stack_with_an_unknown_name_names_the_stacks_that_exist() -> None:
    box, _ = _toolbox(sharing=FULL)

    out = _call(box, "get_virtual_chassis", virtual_chassis="nope")

    assert out.is_error and "No virtual chassis 'nope'" in out.content
    assert "Available: LAB.local.zz" in out.content


# -- totals ("how many") ---------------------------------------------------------------------


def test_a_list_with_more_pages_gives_the_model_the_total() -> None:
    nautobot = FakeNautobot()
    nautobot.has_more = True
    box, _ = _toolbox(nautobot, sharing=FULL)

    data = _data(_call(box, "list_devices", role="network", limit=1))

    assert (data["total"], data["total_exact"]) == (137, True)
    assert nautobot.count_calls == [("devices", {"role": ["Network"]})]


def test_the_total_of_ip_addresses_is_not_counted_without_the_addresses_switch() -> None:
    nautobot = FakeNautobot()
    nautobot.has_more = True
    box, _ = _toolbox(nautobot, sharing=BASIC)

    data = _data(_call(box, "list_ip_addresses"))

    assert data["not_shared"] == "device_addresses" and "total" not in data
    assert nautobot.requests == 0  # not even a count request


def test_a_stack_list_reports_its_total_too() -> None:
    nautobot = FakeNautobot()
    nautobot.has_more = True
    box, _ = _toolbox(nautobot, sharing=FULL)

    assert _data(_call(box, "list_virtual_chassis"))["total"] == 137


def test_the_service_client_counts_through_rest_with_the_filters_in_the_query_string() -> None:
    service = _RestService({"count": 12, "results": []})

    client = NautobotServiceClient(service, CREDENTIALS)
    count = asyncio.run(client.count("devices", {"tags": ["lab"]}))

    assert (count.total, count.exact) == (12, True)
    endpoint = "dcim/devices/?tags=lab&limit=1&brief=true"
    assert service.calls == [(endpoint, "GET", None, CREDENTIALS)]


def test_a_failed_rest_get_does_not_chain_the_endpoint_with_its_filter_values() -> None:
    # The service's error message holds the whole endpoint (device names, addresses, search
    # text); the chain would carry it into logs and error trackers.
    url = "dcim/devices/?name__ic=secret-host"
    error = NautobotAPIError(f"Resource not found: {url}", http_status=404)
    client = NautobotServiceClient(_RestService(error=error), CREDENTIALS)

    with pytest.raises(QueryError) as raised:
        asyncio.run(client.rest_get("dcim/devices/?name__ic=secret-host&limit=1&brief=true"))

    assert raised.value.__cause__ is None and raised.value.__suppress_context__
    assert "secret-host" not in str(raised.value)
