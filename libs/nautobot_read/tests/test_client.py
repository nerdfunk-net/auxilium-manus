from typing import Any

import pytest

from nautobot_read.client import GraphQLClient, NautobotError


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
