import pytest

from nautobot_mcp.config import Config, ConfigError


def test_loads_required_values_and_defaults():
    cfg = Config.from_env({"NAUTOBOT_URL": "http://nb:8080/", "NAUTOBOT_TOKEN": "tok"})
    assert cfg.url == "http://nb:8080"  # trailing slash stripped
    assert cfg.token == "tok"
    assert cfg.verify_ssl is True


@pytest.mark.parametrize("missing", ["NAUTOBOT_URL", "NAUTOBOT_TOKEN"])
def test_missing_required_value_fails_fast(missing):
    env = {"NAUTOBOT_URL": "http://nb", "NAUTOBOT_TOKEN": "tok"}
    del env[missing]
    with pytest.raises(ConfigError, match=missing):
        Config.from_env(env)


def test_rejects_non_http_url():
    with pytest.raises(ConfigError, match="NAUTOBOT_URL"):
        Config.from_env({"NAUTOBOT_URL": "ftp://nb", "NAUTOBOT_TOKEN": "tok"})


@pytest.mark.parametrize(("raw", "expected"), [("false", False), ("0", False), ("true", True)])
def test_verify_ssl_flag(raw, expected):
    env = {"NAUTOBOT_URL": "http://nb", "NAUTOBOT_TOKEN": "tok", "NAUTOBOT_VERIFY_SSL": raw}
    assert Config.from_env(env).verify_ssl is expected


def test_repr_never_contains_the_token():
    cfg = Config.from_env({"NAUTOBOT_URL": "http://nb", "NAUTOBOT_TOKEN": "s3cret-token"})
    assert "s3cret-token" not in repr(cfg)


@pytest.mark.parametrize(
    "url",
    ["http://169.254.169.254", "https://metadata.google.internal", "http://u:p@nb",
     "http://nb.example.com", "https://"],
)
def test_rejects_unsafe_urls(url):
    with pytest.raises(ConfigError):
        Config.from_env({"NAUTOBOT_URL": url, "NAUTOBOT_TOKEN": "tok"})


@pytest.mark.parametrize(
    "url",
    ["http://localhost:8080", "http://127.0.0.1", "http://10.1.2.3", "http://nautobot:8080",
     "http://host.docker.internal:8080", "https://nb.example.com", "http://[::1]:8080"],
)
def test_accepts_local_cleartext_and_any_https(url):
    assert Config.from_env({"NAUTOBOT_URL": url, "NAUTOBOT_TOKEN": "tok"}).token == "tok"


def test_cleartext_to_a_remote_host_needs_an_explicit_opt_in():
    env = {"NAUTOBOT_URL": "http://nb.example.com", "NAUTOBOT_TOKEN": "tok",
           "NAUTOBOT_ALLOW_INSECURE_HTTP": "true"}
    assert Config.from_env(env).url == "http://nb.example.com"
