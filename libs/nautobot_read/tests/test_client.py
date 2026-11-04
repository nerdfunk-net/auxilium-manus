from typing import Any

import pytest

from nautobot_read.client import (
    COUNT_FALLBACK_CAP,
    REST_LIST_ENDPOINTS,
    Count,
    GraphQLClient,
    NautobotError,
    RestNotSupported,
)


class ScriptedClient(GraphQLClient):
    """Answers each query with the next canned response and records what was sent."""

    def __init__(self, *responses: list[dict[str, Any]]) -> None:
        self._responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def graphql(self, query, variables=None):
        self.calls.append((query, variables or {}))
        rows = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        return {"devices": rows}


def rows(*names):
    return [{"name": n} for n in names]


async def test_list_page_asks_for_one_extra_row_to_detect_more():
    client = ScriptedClient(rows("a", "b", "c"))
    page = await client.list_page("devices", "name", {"role": ["Network"]}, limit=2, offset=0)
    assert page.items == ({"name": "a"}, {"name": "b"})
    assert page.has_more is True
    query, variables = client.calls[-1]
    assert variables["limit"] == 3  # limit + 1
    assert "$f_role" in query and variables["f_role"] == ["Network"]


async def test_list_page_last_page_has_no_more():
    page = await ScriptedClient(rows("a")).list_page("devices", "name", {}, limit=2, offset=4)
    assert page.items == ({"name": "a"},)
    assert page.has_more is False


async def test_list_page_treats_a_missing_root_as_no_rows():
    class Empty(ScriptedClient):
        async def graphql(self, query, variables=None):
            return {}

    page = await Empty([]).list_page("devices", "name", {}, limit=2, offset=0)
    assert page.items == () and page.has_more is False


async def test_list_page_skips_empty_filters():
    client = ScriptedClient(rows("a"))
    await client.list_page("devices", "name", {"role": [], "status": None}, limit=1, offset=0)
    query, variables = client.calls[-1]
    assert "$f_role" not in query and "$f_status" not in query
    assert "f_role" not in variables


async def test_filter_values_travel_as_variables_not_in_the_query_text():
    client = ScriptedClient(rows("a"))
    await client.list_page("devices", "name", {"name": ['x") { evil }']}, limit=1, offset=0)
    query, variables = client.calls[-1]
    assert "evil" not in query
    assert variables["f_name"] == ['x") { evil }']


async def test_list_page_rejects_unsafe_identifiers():
    with pytest.raises(ValueError, match="identifier"):
        await ScriptedClient(rows("a")).list_page(
            "devices", "name", {"role) { x } #": ["a"]}, limit=1, offset=0
        )


async def test_list_all_follows_pages_until_exhausted():
    client = ScriptedClient(rows("a", "b", "c"), rows("d"))
    result = await client.list_all("devices", "name", page_size=2)
    assert [r["name"] for r in result] == ["a", "b", "d"]
    assert [v["offset"] for _, v in client.calls] == [0, 2]


async def test_list_all_raises_instead_of_truncating_at_max_items():
    # Every page reports more rows: silently dropping them would make later lookups (for
    # example a location beyond the cap) fail with a misleading "No location ...".
    with pytest.raises(NautobotError, match="more than 3 devices"):
        await ScriptedClient(rows("a", "b", "c")).list_all(
            "devices", "name", page_size=2, max_items=3
        )


async def test_list_all_accepts_exactly_max_items():
    client = ScriptedClient(rows("a", "b", "c"), rows("c"))
    result = await client.list_all("devices", "name", page_size=2, max_items=3)
    assert [r["name"] for r in result] == ["a", "b", "c"]


async def test_graphql_is_abstract():
    with pytest.raises(TypeError):
        GraphQLClient()  # type: ignore[abstract]


class RestClient(ScriptedClient):
    """A client that can do REST: records the endpoints and answers with ``reply``."""

    def __init__(self, reply: Any, *responses: list[dict[str, Any]]) -> None:
        super().__init__(*responses)
        self.reply = reply
        self.endpoints: list[str] = []

    async def rest_get(self, endpoint):
        self.endpoints.append(endpoint)
        return self.reply


async def test_the_default_rest_get_says_it_is_not_supported():
    with pytest.raises(RestNotSupported, match="cannot call the REST API"):
        await ScriptedClient(rows("a")).rest_get("dcim/devices/")


async def test_count_asks_rest_for_one_row_and_reads_the_total():
    client = RestClient({"count": 137, "results": []})
    count = await client.count("devices", {"tags": ["lab"], "role": None})
    assert count == Count(137, exact=True)
    assert client.endpoints == ["dcim/devices/?tags=lab&limit=1&brief=true"]
    assert client.calls == []  # GraphQL was not used


async def test_count_repeats_a_key_for_several_values_and_encodes_the_values():
    client = RestClient({"count": 2})
    await client.count("prefixes", {"within_include": ["10.0.0.0/8", "a b&c=d"]})
    assert client.endpoints == [
        "ipam/prefixes/?within_include=10.0.0.0%2F8&within_include=a+b%26c%3Dd&limit=1&brief=true"
    ]


@pytest.mark.parametrize("reply", [None, [], {"count": "7"}, {"count": True}, {"count": -1}])
async def test_count_rejects_an_unexpected_rest_answer(reply):
    with pytest.raises(NautobotError, match="unexpected response"):
        await RestClient(reply).count("devices", {})


@pytest.mark.parametrize("reply", [{"count": None, "results": []}, {"results": []}, {}])
async def test_count_falls_back_to_graphql_when_rest_has_no_usable_count(reply):
    # Nautobot answers ``count: null`` when its count query times out: still answerable.
    client = RestClient(reply, rows(*"a" * 30))
    assert await client.count("devices", {}) == Count(30, exact=True)
    assert len(client.endpoints) == 1 and len(client.calls) == 1


async def test_count_lets_a_rest_failure_reach_the_caller():
    class Failing(ScriptedClient):
        async def rest_get(self, endpoint):
            raise NautobotError("Nautobot returned an error (HTTP 500).")

    with pytest.raises(NautobotError, match="HTTP 500"):
        await Failing(rows("a")).count("devices", {})


@pytest.mark.parametrize("root", ["devices; drop", "1devices"])
async def test_count_rejects_a_root_that_is_not_a_plain_identifier(root):
    with pytest.raises(ValueError, match="plain identifier"):
        await RestClient({"count": 1}).count(root, {})


async def test_count_rejects_a_filter_name_that_is_not_a_plain_identifier():
    with pytest.raises(ValueError, match="plain identifier"):
        await RestClient({"count": 1}).count("devices", {"a&limit=9": ["x"]})


async def test_count_without_rest_pages_ids_and_is_exact_below_the_cap():
    client = ScriptedClient(rows(*"a" * 201), rows(*"b" * 30))
    count = await client.count("devices", {"role": ["Network"]})
    assert count == Count(230, exact=True)
    assert [v["offset"] for _, v in client.calls] == [0, 200]
    assert all("id" in q and v["limit"] == 201 for q, v in client.calls)


async def test_count_without_rest_stops_at_the_cap_and_says_it_is_a_lower_bound():
    client = ScriptedClient(rows(*"a" * 201))  # every page has more
    count = await client.count("devices", {})
    assert count == Count(COUNT_FALLBACK_CAP, exact=False)
    assert len(client.calls) == COUNT_FALLBACK_CAP // 200


async def test_count_of_a_root_without_a_rest_endpoint_pages_graphql():
    class Namespaces(RestClient):
        async def graphql(self, query, variables=None):
            return {"namespaces": rows("a")}

    client = Namespaces({"count": 999})
    count = await client.count("namespaces", {})
    assert count == Count(1, exact=True)
    assert client.endpoints == []


def test_every_endpoint_in_the_map_is_a_plain_rest_path():
    assert set(REST_LIST_ENDPOINTS) == {
        "devices", "interfaces", "locations", "ip_addresses", "prefixes", "virtual_chassis",
    }
    assert all(p.count("/") == 1 and not p.startswith("/") for p in REST_LIST_ENDPOINTS.values())


async def test_list_page_declares_a_boolean_filter_as_boolean_and_keeps_false():
    client = ScriptedClient(rows("a"))
    await client.list_page(
        "interfaces", "name", {"has_cable": True, "enabled": False, "role": None},
        limit=1, offset=0,
    )
    query, variables = client.calls[-1]
    assert "$f_has_cable: Boolean" in query and variables["f_has_cable"] is True
    assert "$f_enabled: Boolean" in query and variables["f_enabled"] is False
    assert "$f_role" not in query


async def test_count_sends_a_boolean_filter_to_rest_as_true_or_false():
    client = RestClient({"count": 3})
    await client.count("interfaces", {"device_id": ["d1"], "has_cable": True, "enabled": False})
    assert client.endpoints == [
        "dcim/interfaces/?device_id=d1&has_cable=true&enabled=false&limit=1&brief=true"
    ]
