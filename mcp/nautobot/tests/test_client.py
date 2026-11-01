import httpx
import pytest
import respx
from nautobot_read.client import NautobotError

from nautobot_mcp.client import NautobotClient
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
async def test_graphql_errors_reach_the_model_as_a_fixed_sentence_only(client, caplog):
    # Nautobot's message (schema hints, choice lists, fragments of internals) must not become
    # model context; the operator reads it in the server log.
    respx.post(GRAPHQL).mock(
        return_value=httpx.Response(
            200,
            json={"errors": [{"message": "{'role': ['Select a valid choice. Nope is not one']}"}]},
        )
    )
    with caplog.at_level("WARNING", logger="nautobot_mcp.client"):
        with pytest.raises(NautobotError) as exc:
            await client.graphql("{devices{name}}")
    assert str(exc.value) == "Nautobot rejected the query."
    assert "Select a valid choice" not in str(exc.value)
    assert "s3cret-token" not in str(exc.value)
    assert "Select a valid choice" in caplog.text


@respx.mock
async def test_graphql_errors_on_http_400_are_the_same_fixed_sentence(client, caplog):
    respx.post(GRAPHQL).mock(
        return_value=httpx.Response(
            400, json={"errors": [{"message": "Unknown argument 'x' on field 'Query.devices'."}]}
        )
    )
    with caplog.at_level("WARNING", logger="nautobot_mcp.client"):
        with pytest.raises(NautobotError) as exc:
            await client.graphql("{devices(x:1){name}}")
    assert str(exc.value) == "Nautobot rejected the query."
    assert "Unknown argument" in caplog.text


@respx.mock
async def test_the_logged_graphql_error_text_is_bounded(client, caplog):
    respx.post(GRAPHQL).mock(
        return_value=httpx.Response(200, json={"errors": [{"message": "x" * 5000}, "plain"]})
    )
    with caplog.at_level("WARNING", logger="nautobot_mcp.client"):
        with pytest.raises(NautobotError):
            await client.graphql("{devices{name}}")
    assert "x" * 500 in caplog.text and "x" * 501 not in caplog.text


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
