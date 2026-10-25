from pathlib import Path

import pytest

from manus_agent.config import ConfigError, load_config

SECRET = "s" * 40


def env(**overrides: str) -> dict[str, str]:
    base = {
        "MANUS_AGENT_ID": "geo-agent",
        "MANUS_AGENT_SECRET": SECRET,
        "MANUS_AGENT_HTTP_PORT": "8080",
    }
    base.update(overrides)
    return {k: v for k, v in base.items() if v is not None}


def test_http_only_defaults():
    config = load_config(env())
    assert config.agent_id == "geo-agent"
    assert config.secret == SECRET
    assert config.http_port == 8080
    assert config.http_host == "0.0.0.0"
    assert config.redis_url is None
    assert config.max_concurrency == 4
    assert config.handlers_dir == Path("handlers")


def test_redis_only():
    config = load_config(env(MANUS_AGENT_HTTP_PORT=None, MANUS_AGENT_REDIS_URL="rediss://u:p@h:6379/0"))
    assert config.http_port is None
    assert config.redis_url == "rediss://u:p@h:6379/0"


def test_both_transports_at_once():
    config = load_config(env(MANUS_AGENT_REDIS_URL="redis://localhost"))
    assert config.http_port == 8080 and config.redis_url


def test_needs_at_least_one_transport():
    with pytest.raises(ConfigError, match="MANUS_AGENT_HTTP_PORT"):
        load_config(env(MANUS_AGENT_HTTP_PORT=None))


@pytest.mark.parametrize("agent_id", ["", "Has Space", "UPPER", "x" * 65, "1abc"])
def test_agent_id_rules(agent_id):
    with pytest.raises(ConfigError, match="MANUS_AGENT_ID"):
        load_config(env(MANUS_AGENT_ID=agent_id))


def test_secret_is_required_and_long():
    with pytest.raises(ConfigError, match="MANUS_AGENT_SECRET"):
        load_config(env(MANUS_AGENT_SECRET=None))
    with pytest.raises(ConfigError, match="32"):
        load_config(env(MANUS_AGENT_SECRET="short"))


def test_error_never_contains_the_secret():
    with pytest.raises(ConfigError) as ctx:
        load_config(env(MANUS_AGENT_SECRET="tooshort-secret"))
    assert "tooshort-secret" not in str(ctx.value)


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("MANUS_AGENT_HTTP_PORT", "0"),
        ("MANUS_AGENT_HTTP_PORT", "70000"),
        ("MANUS_AGENT_HTTP_PORT", "http"),
        ("MANUS_AGENT_MAX_CONCURRENCY", "0"),
        ("MANUS_AGENT_MAX_CONCURRENCY", "65"),
        ("MANUS_AGENT_MAX_BODY_BYTES", "100"),
        ("MANUS_AGENT_MAX_RESPONSE_BYTES", "100"),
        ("MANUS_AGENT_REDIS_URL", "http://not-redis"),
    ],
)
def test_bad_values(name, value):
    with pytest.raises(ConfigError, match=name):
        load_config(env(**{name: value}))


def test_optional_settings():
    config = load_config(
        env(
            MANUS_AGENT_HTTP_HOST="127.0.0.1",
            MANUS_AGENT_HANDLERS_DIR="/opt/handlers",
            MANUS_AGENT_MAX_CONCURRENCY="9",
            MANUS_AGENT_LOGLEVEL="debug",
        )
    )
    assert (config.http_host, config.handlers_dir, config.max_concurrency) == (
        "127.0.0.1",
        Path("/opt/handlers"),
        9,
    )
    assert config.loglevel == "DEBUG"


def test_response_limit_default_and_override():
    assert load_config(env()).max_response_bytes == 16 * 1_048_576
    assert load_config(env(MANUS_AGENT_MAX_RESPONSE_BYTES="4096")).max_response_bytes == 4096


def test_config_repr_hides_the_secret():
    assert SECRET not in repr(load_config(env()))
