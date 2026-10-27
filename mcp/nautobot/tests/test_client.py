import httpx
import pytest
import respx

from nautobot_mcp.client import NautobotClient, NautobotError
from nautobot_mcp.config import Config

CONFIG = Config(url="http://nb.test", token="s3cret-token")
GRAPHQL = "http://nb.test/api/graphql/"


@pytest.fixture
async def client():
    async with NautobotClient(CONFIG) as nautobot:
        yield nautobot


@respx.mock
async def test_graphql_sends_token_and_returns_data(client):
    route = respx.post(GRAPHQL).mock(
        return_value=httpx.Response(200, json={"data": {"devices": [{"name": "d1"}]}})
    )
    data = await client.graphql("query($n:[String]){devices(name:$n){name}}", {"n": ["d1"]})
    assert data == {"devices": [{"name": "d1"}]}
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Token s3cret-token"
    assert b'"variables"' in request.content


@respx.mock
async def test_graphql_errors_become_nautobot_error_without_the_token(client):
    respx.post(GRAPHQL).mock(
        return_value=httpx.Response(
            200,
            json={"errors": [{"message": "{'role': ['Select a valid choice. Nope is not one']}"}]},
        )
    )
    with pytest.raises(NautobotError) as exc:
        await client.graphql("{devices{name}}")
    assert "Select a valid choice" in str(exc.value)
    assert "s3cret-token" not in str(exc.value)


@respx.mock
async def test_unknown_argument_http_400_is_reported(client):
    respx.post(GRAPHQL).mock(
        return_value=httpx.Response(
            400, json={"errors": [{"message": "Unknown argument 'x' on field 'Query.devices'."}]}
        )
    )
    with pytest.raises(NautobotError, match="Unknown argument"):
        await client.graphql("{devices(x:1){name}}")


@pytest.mark.parametrize(("status", "hint"), [(401, "token"), (403, "permission"), (500, "500")])
@respx.mock
async def test_http_failures_get_short_actionable_messages(client, status, hint):
    respx.post(GRAPHQL).mock(return_value=httpx.Response(status, text="<html>boom</html>"))
    with pytest.raises(NautobotError) as exc:
        await client.graphql("{devices{name}}")
    assert hint in str(exc.value)
    assert "<html>" not in str(exc.value)


@respx.mock
async def test_connection_failure_does_not_leak_internals(client):
    respx.post(GRAPHQL).mock(side_effect=httpx.ConnectError("[Errno 61] refused 10.1.2.3"))
    with pytest.raises(NautobotError) as exc:
        await client.graphql("{devices{name}}")
    assert "reach Nautobot" in str(exc.value)
    assert "10.1.2.3" not in str(exc.value)


@respx.mock
async def test_non_json_response_is_an_error(client):
    respx.post(GRAPHQL).mock(return_value=httpx.Response(200, text="not json"))
    with pytest.raises(NautobotError, match="unexpected response"):
        await client.graphql("{devices{name}}")


def _page(*names):
    return httpx.Response(200, json={"data": {"devices": [{"name": n} for n in names]}})


@respx.mock
async def test_list_page_asks_for_one_extra_row_to_detect_more(client):
    route = respx.post(GRAPHQL).mock(return_value=_page("a", "b", "c"))
    page = await client.list_page("devices", "name", {"role": ["Network"]}, limit=2, offset=0)
    assert page.items == ({"name": "a"}, {"name": "b"})
    assert page.has_more is True
    body = route.calls.last.request.content.decode()
    assert '"limit":3' in body.replace(" ", "")  # limit + 1
    assert "$f_role" in body
    assert '"f_role":["Network"]' in body.replace(" ", "")


@respx.mock
async def test_list_page_last_page_has_no_more(client):
    respx.post(GRAPHQL).mock(return_value=_page("a"))
    page = await client.list_page("devices", "name", {}, limit=2, offset=4)
    assert page.items == ({"name": "a"},)
    assert page.has_more is False


@respx.mock
async def test_list_page_skips_empty_filters(client):
    route = respx.post(GRAPHQL).mock(return_value=_page("a"))
    await client.list_page("devices", "name", {"role": [], "status": None}, limit=1, offset=0)
    body = route.calls.last.request.content.decode()
    assert "$f_role" not in body
    assert "$f_status" not in body


async def test_list_page_rejects_unsafe_identifiers(client):
    with pytest.raises(ValueError, match="identifier"):
        await client.list_page("devices", "name", {"role) { x } #": ["a"]}, limit=1, offset=0)


@respx.mock
async def test_list_all_follows_pages_until_exhausted(client):
    respx.post(GRAPHQL).mock(side_effect=[_page("a", "b", "c"), _page("d")])
    rows = await client.list_all("devices", "name", page_size=2)
    assert [r["name"] for r in rows] == ["a", "b", "d"]


@respx.mock
async def test_list_all_stops_at_max_items(client):
    respx.post(GRAPHQL).mock(return_value=_page("a", "b", "c"))
    rows = await client.list_all("devices", "name", page_size=2, max_items=3)
    assert len(rows) == 3
