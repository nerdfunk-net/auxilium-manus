import httpx
import respx

from nautobot_mcp import __main__ as entry
from nautobot_mcp.config import Config

GRAPHQL = "http://nb.test/api/graphql/"


def test_main_exits_2_with_a_clear_message_when_config_is_missing(monkeypatch, capsys):
    monkeypatch.delenv("NAUTOBOT_URL", raising=False)
    monkeypatch.delenv("NAUTOBOT_TOKEN", raising=False)
    assert entry.main() == 2
    captured = capsys.readouterr()
    assert "NAUTOBOT_URL is not set" in captured.err
    assert captured.out == ""  # stdout is reserved for the MCP protocol


@respx.mock
async def test_serve_builds_instructions_from_live_data_then_runs_stdio(monkeypatch):
    def reply(request):
        query = request.content.decode()
        if "roles" in query:
            data = {"roles": [{"name": "Network"}]}
        elif "statuses" in query:
            data = {"statuses": [{"name": "Active"}]}
        elif "location_types" in query:
            data = {"location_types": [{"name": "Country"}]}
        else:
            data = {"locations": []}
        return httpx.Response(200, json={"data": data})

    respx.post(GRAPHQL).mock(side_effect=reply)
    seen = {}

    class FakeServer:
        async def run_stdio_async(self):
            seen["ran"] = True

    def fake_build(app, *, instructions):
        seen["instructions"] = instructions
        return FakeServer()

    monkeypatch.setattr(entry, "build_server", fake_build)
    await entry._serve(Config(url="http://nb.test", token="tok"))
    assert seen["ran"] is True
    assert "Device roles: Network" in seen["instructions"]


def test_main_runs_the_server_with_a_valid_config(monkeypatch):
    monkeypatch.setenv("NAUTOBOT_URL", "http://nb.test")
    monkeypatch.setenv("NAUTOBOT_ALLOW_INSECURE_HTTP", "true")
    monkeypatch.setenv("NAUTOBOT_TOKEN", "tok")
    served = []

    async def fake_serve(config):
        served.append(config.url)

    monkeypatch.setattr(entry, "_serve", fake_serve)
    assert entry.main() == 0
    assert served == ["http://nb.test"]


def test_unknown_transport_exits_2(monkeypatch, capsys):
    monkeypatch.setenv("NAUTOBOT_URL", "http://nb.test")
    monkeypatch.setenv("NAUTOBOT_ALLOW_INSECURE_HTTP", "true")
    monkeypatch.setenv("NAUTOBOT_TOKEN", "tok")
    monkeypatch.setenv("MCP_TRANSPORT", "carrier-pigeon")
    assert entry.main() == 2
    assert "MCP_TRANSPORT" in capsys.readouterr().err


def test_http_transport_without_client_tokens_exits_2(monkeypatch, capsys):
    monkeypatch.setenv("NAUTOBOT_URL", "http://nb.test")
    monkeypatch.setenv("NAUTOBOT_ALLOW_INSECURE_HTTP", "true")
    monkeypatch.setenv("NAUTOBOT_TOKEN", "tok")
    monkeypatch.setenv("MCP_TRANSPORT", "http")
    monkeypatch.delenv("MCP_CLIENT_TOKENS", raising=False)
    monkeypatch.delenv("MCP_CLIENT_TOKENS_FILE", raising=False)
    assert entry.main() == 2
    assert "at least one client token" in capsys.readouterr().err


def test_http_transport_runs_the_http_server(monkeypatch):
    monkeypatch.setenv("NAUTOBOT_URL", "http://nb.test")
    monkeypatch.setenv("NAUTOBOT_ALLOW_INSECURE_HTTP", "true")
    monkeypatch.setenv("NAUTOBOT_TOKEN", "tok")
    monkeypatch.setenv("MCP_TRANSPORT", "HTTP")
    monkeypatch.setenv("MCP_CLIENT_TOKENS", "ui=" + "x" * 32)
    monkeypatch.setenv("MCP_PORT", "9123")
    served = []

    async def fake_serve_http(config, http_config):
        served.append((config.url, http_config.port))

    monkeypatch.setattr(entry, "_serve_http", fake_serve_http)
    assert entry.main() == 0
    assert served == [("http://nb.test", 9123)]


@respx.mock
async def test_serve_http_builds_the_app_and_hands_it_to_uvicorn(monkeypatch):
    respx.post(GRAPHQL).mock(
        return_value=httpx.Response(200, json={"data": {"roles": [], "statuses": [],
                                                        "location_types": [], "locations": []}})
    )
    seen = {}

    class FakeUvicorn:
        def __init__(self, config):
            seen["config"] = config

        async def serve(self):
            seen["served"] = True

    monkeypatch.setattr(entry.uvicorn, "Server", FakeUvicorn)
    http_config = entry.HttpConfig.from_env({"MCP_CLIENT_TOKENS": "ui=" + "x" * 32})
    await entry._serve_http(Config(url="http://nb.test", token="tok"), http_config)
    assert seen["served"] is True
    assert (seen["config"].host, seen["config"].port) == ("127.0.0.1", 8000)
    assert seen["config"].server_header is False
