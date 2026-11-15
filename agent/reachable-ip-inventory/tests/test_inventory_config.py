import ipaddress
import os
import tempfile
import unittest
from pathlib import Path

from manus_agent.inventory_config import (
    ConfigFileError,
    InventoryConfig,
    load_inventory_config,
    parse_inventory_config,
)

MINIMAL = {"nautobot": {"url": "https://nb.example.com/", "token": "inline-token"}}


def parse(raw, env=None) -> InventoryConfig:
    return parse_inventory_config(raw, env or {})


class DefaultsTests(unittest.TestCase):
    def test_minimal_file_gets_the_defaults(self) -> None:
        config = parse(MINIMAL)
        assert config.nautobot.url == "https://nb.example.com"  # trailing slash removed
        assert config.nautobot.verify_ssl is True
        assert config.nautobot.timeout_seconds == 15
        assert config.nautobot.max_prefixes == 100
        assert (config.scan.count, config.scan.timeout_ms, config.scan.max_hosts) == (1, 500, 4096)
        assert config.dns.enabled is False and config.dns.timeout_seconds == 2
        assert ipaddress.ip_network("192.168.1.0/24").subnet_of(config.scan.allowed[2])
        assert len(config.scan.allowed) == 3

    def test_allowed_networks_as_list_or_text(self) -> None:
        for value in (["10.1.0.0/16"], "10.1.0.0/16"):
            config = parse({**MINIMAL, "scan": {"allowed_networks": value}})
            assert [str(n) for n in config.scan.allowed] == ["10.1.0.0/16"]

    def test_empty_allowed_networks_means_private_space(self) -> None:
        for value in ([], "", None):
            config = parse({**MINIMAL, "scan": {"allowed_networks": value}})
            assert len(config.scan.allowed) == 3


class TokenTests(unittest.TestCase):
    def test_environment_variable_wins_over_the_inline_token(self) -> None:
        raw = {"nautobot": {"url": "http://nb", "token_env": "NB_TOKEN", "token": "inline"}}
        assert parse(raw, {"NB_TOKEN": " from-env "}).nautobot.token == "from-env"

    def test_inline_token_is_used_when_the_variable_is_empty(self) -> None:
        raw = {"nautobot": {"url": "http://nb", "token_env": "NB_TOKEN", "token": "inline"}}
        assert parse(raw, {"NB_TOKEN": ""}).nautobot.token == "inline"

    def test_no_token_at_all_is_refused_naming_the_variable(self) -> None:
        raw = {"nautobot": {"url": "http://nb", "token_env": "NB_TOKEN"}}
        with self.assertRaisesRegex(ConfigFileError, "NB_TOKEN is not set"):
            parse(raw, {})
        with self.assertRaisesRegex(ConfigFileError, "no token given"):
            parse({"nautobot": {"url": "http://nb"}})

    def test_bad_token_settings(self) -> None:
        for nautobot in (
            {"token_env": "not a name"},
            {"token_env": 5},
            {"token": ""},
            {"token": 5},
        ):
            with self.subTest(nautobot=nautobot), self.assertRaises(ConfigFileError):
                parse({"nautobot": {"url": "http://nb", **nautobot}})

    def test_the_token_is_never_in_repr_or_errors(self) -> None:
        config = parse(MINIMAL)
        assert "inline-token" not in repr(config)
        with self.assertRaises(ConfigFileError) as caught:
            parse({"nautobot": {"url": "ftp://nb", "token": "inline-token"}})
        assert "inline-token" not in str(caught.exception)


class ValidationTests(unittest.TestCase):
    def assert_refused(self, raw, pattern: str) -> None:
        with self.assertRaisesRegex(ConfigFileError, pattern):
            parse(raw)

    def test_structure(self) -> None:
        self.assert_refused([], "mapping")
        self.assert_refused({}, "nautobot: section is required")
        self.assert_refused({**MINIMAL, "extra": {}}, "unknown section 'extra'")
        self.assert_refused({"nautobot": []}, "nautobot: must be a mapping")
        self.assert_refused({"nautobot": {**MINIMAL["nautobot"], "x": 1}}, "unknown key 'x'")
        self.assert_refused({**MINIMAL, "scan": {"y": 1}}, "scan: unknown key 'y'")

    def test_url(self) -> None:
        for url in (
            None,
            " ",
            "nb.example.com",
            "ftp://nb",
            "https://u:p@nb",
            "https://nb?x=1",
            "https://",
        ):
            with self.subTest(url=url):
                self.assert_refused({"nautobot": {"url": url, "token": "t"}}, "nautobot.url")

    def test_the_url_may_not_point_at_a_blocked_host(self) -> None:
        for url in (
            "http://169.254.169.254",
            "http://169.254.169.254/latest",
            "http://metadata.google.internal",
            "https://metadata.google.com:443",
            "http://METADATA.GOOGLE.INTERNAL./",
            "http://[::ffff:169.254.169.254]",
            "http://0.0.0.0:8080",
            "http://224.0.0.1",
            "http://[fe80::1]",
        ):
            with self.subTest(url=url):
                self.assert_refused({"nautobot": {"url": url, "token": "t"}}, "host is not allowed")

    def test_loopback_and_private_hosts_stay_allowed(self) -> None:
        for url in (
            "http://127.0.0.1:8080",
            "http://localhost:8080",
            "https://nautobot:8443",
            "http://10.0.0.5",
        ):
            with self.subTest(url=url):
                assert parse({"nautobot": {"url": url, "token": "t"}}).nautobot.url == url

    def test_numbers_and_flags(self) -> None:
        nb = MINIMAL["nautobot"]
        self.assert_refused({"nautobot": {**nb, "verify_ssl": "yes"}}, "verify_ssl")
        self.assert_refused({"nautobot": {**nb, "timeout_seconds": 0}}, "between")
        self.assert_refused({"nautobot": {**nb, "max_prefixes": 1.5}}, "whole number")
        self.assert_refused({**MINIMAL, "scan": {"count": True}}, "scan.count")
        self.assert_refused({**MINIMAL, "scan": {"count": 6}}, "between 1 and 5")
        self.assert_refused({**MINIMAL, "scan": {"max_hosts": 70000}}, "scan.max_hosts")
        self.assert_refused({**MINIMAL, "resolve_dns": {"enabled": 1}}, "resolve_dns.enabled")
        self.assert_refused({**MINIMAL, "resolve_dns": {"timeout_seconds": 11}}, "between")

    def test_allowed_networks(self) -> None:
        self.assert_refused({**MINIMAL, "scan": {"allowed_networks": "nonsense"}}, "IPv4 networks")
        self.assert_refused({**MINIMAL, "scan": {"allowed_networks": [5]}}, "list of IPv4")
        self.assert_refused({**MINIMAL, "scan": {"allowed_networks": 5}}, "list of IPv4")


class LoadTests(unittest.TestCase):
    def write(self, text: str) -> dict[str, str]:
        directory = Path(tempfile.mkdtemp())
        path = directory / "config.yaml"
        path.write_text(text)
        return {"MANUS_AGENT_CONFIG": str(path)}

    def test_loads_the_named_file(self) -> None:
        env = self.write(
            "nautobot:\n  url: http://nb\n  token_env: T\nresolve_dns:\n  enabled: true\n"
        )
        config = load_inventory_config({**env, "T": "secret-value"})
        assert config.nautobot.token == "secret-value" and config.dns.enabled

    def test_errors_name_the_file_and_not_the_content(self) -> None:
        env = self.write("nautobot: [")
        with self.assertRaisesRegex(ConfigFileError, "config.yaml: is not valid YAML"):
            load_inventory_config(env)
        env = self.write("nautobot:\n  url: ftp://x\n  token: t\n")
        with self.assertRaisesRegex(ConfigFileError, "config.yaml: nautobot.url"):
            load_inventory_config(env)

    def test_missing_and_oversized_files(self) -> None:
        with self.assertRaisesRegex(ConfigFileError, "cannot be read"):
            load_inventory_config({"MANUS_AGENT_CONFIG": "/nonexistent/config.yaml"})
        env = self.write("# " + "x" * (256 * 1024) + "\n")
        with self.assertRaisesRegex(ConfigFileError, "larger than"):
            load_inventory_config(env)

    def test_default_path_is_config_yaml_in_the_working_directory(self) -> None:
        previous = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        try:
            with self.assertRaisesRegex(ConfigFileError, "config.yaml"):
                load_inventory_config({})
        finally:
            os.chdir(previous)
