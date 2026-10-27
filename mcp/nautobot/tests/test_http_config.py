import pytest

from nautobot_mcp.config import ConfigError
from nautobot_mcp.http_config import HttpConfig

TOKEN_A = "a" * 32
TOKEN_B = "b" * 40


def env(**extra):
    return {"MCP_CLIENT_TOKENS": f"ui={TOKEN_A}", **extra}


def test_loopback_defaults():
    cfg = HttpConfig.from_env(env())
    assert (cfg.host, cfg.port) == ("127.0.0.1", 8000)
    assert "localhost:*" in cfg.allowed_hosts and "127.0.0.1:*" in cfg.allowed_hosts
    assert [(c.name, c.token) for c in cfg.clients] == [("ui", TOKEN_A)]


def test_several_clients_in_the_variable_and_whitespace_is_ignored():
    cfg = HttpConfig.from_env({"MCP_CLIENT_TOKENS": f" ui={TOKEN_A} , ci={TOKEN_B} "})
    assert [c.name for c in cfg.clients] == ["ui", "ci"]


def test_tokens_can_come_from_a_file_and_merge_with_the_variable(tmp_path):
    secrets = tmp_path / "tokens"
    secrets.write_text(f"# clients\n\nci={TOKEN_B}\n")
    cfg = HttpConfig.from_env(env(MCP_CLIENT_TOKENS_FILE=str(secrets)))
    assert sorted(c.name for c in cfg.clients) == ["ci", "ui"]


def test_missing_token_file_is_a_config_error(tmp_path):
    with pytest.raises(ConfigError, match="MCP_CLIENT_TOKENS_FILE"):
        HttpConfig.from_env({"MCP_CLIENT_TOKENS_FILE": str(tmp_path / "nope")})


def test_http_mode_without_any_token_refuses_to_start():
    with pytest.raises(ConfigError, match="at least one client token"):
        HttpConfig.from_env({})


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (f"ui{TOKEN_A}", "name=token"),
        (f"bad name={TOKEN_A}", "client name"),
        ("ui=short", "at least 32"),
        (f"ui={TOKEN_A},ui={TOKEN_B}", "duplicate client name"),
        (f"ui={TOKEN_A},ci={TOKEN_A}", "same token"),
        (f"ui={'a b' * 12}", "whitespace"),
    ],
)
def test_invalid_client_tokens_are_rejected(value, message):
    with pytest.raises(ConfigError, match=message):
        HttpConfig.from_env({"MCP_CLIENT_TOKENS": value})


@pytest.mark.parametrize("port", ["0", "70000", "http"])
def test_invalid_port(port):
    with pytest.raises(ConfigError, match="MCP_PORT"):
        HttpConfig.from_env(env(MCP_PORT=port))


def test_public_bind_requires_allowed_hosts():
    with pytest.raises(ConfigError, match="MCP_ALLOWED_HOSTS"):
        HttpConfig.from_env(env(MCP_HOST="0.0.0.0"))  # noqa: S104


def test_public_bind_with_allowed_hosts():
    cfg = HttpConfig.from_env(
        env(MCP_HOST="0.0.0.0", MCP_ALLOWED_HOSTS="nautobot-mcp:8000, mcp.example.org")  # noqa: S104
    )
    assert cfg.allowed_hosts == ("nautobot-mcp:8000", "mcp.example.org")


def test_repr_never_shows_a_token():
    assert TOKEN_A not in repr(HttpConfig.from_env(env()))
