import copy

import pytest

from manus_agent.data_config import DataConfigError, load_data_config, parse_data_config
from tests.data_helpers import raw_config

URL = "https://git.example.com/org/ips.git"
ENV = {"GIT_TOKEN": "s3cret-token", "MANUS_AGENT_STATE_DIR": "/data"}


def parse(mutate=None, env=ENV):
    raw = copy.deepcopy(raw_config(URL))
    if mutate:
        mutate(raw)
    return parse_data_config(raw, env)


def test_a_valid_config_is_parsed_with_defaults():
    config = parse()
    assert config.git.branch == "main"
    assert config.git.verify_ssl is True
    assert config.git.auth.type == "none"
    assert (config.source.directory, config.source.csv_delimiter) == ("ips", ";")
    assert [r.target for r in config.mapping][:2] == ["name", "interfaces.name"]
    assert "git.example.com" not in repr(config.git)


def test_token_auth_needs_the_environment_variable():
    def use_token(raw):
        raw["git"]["auth"] = {"type": "token", "token_env": "GIT_TOKEN"}

    config = parse(use_token)
    assert (config.git.auth.type, config.git.auth.username) == ("token", "oauth2")
    with pytest.raises(DataConfigError, match="GIT_TOKEN is not set"):
        parse(use_token, env={})


def test_ssh_auth_needs_the_key_file(tmp_path):
    key = tmp_path / "id"
    key.write_text("x")

    def use_key(raw):
        raw["git"]["auth"] = {"type": "ssh", "key_file": str(key)}

    assert parse(use_key).git.auth.key_file == key
    key.unlink()
    with pytest.raises(DataConfigError, match="key_file"):
        parse(use_key)


@pytest.mark.parametrize(
    "path", ["/run/my key", "/run/k;id", "/run/k$(id)", "/run/k`id`", "/run/k\nx", "/run/k'x"]
)
def test_a_key_path_with_shell_characters_is_refused_before_it_is_looked_up(path):
    def use_key(raw):
        raw["git"]["auth"] = {"type": "ssh", "key_file": path}

    with pytest.raises(DataConfigError, match="use only letters"):
        parse(use_key)


def set_at(path, value):
    def mutate(raw):
        node = raw
        for part in path[:-1]:
            node = node[part]
        node[path[-1]] = value

    return mutate


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (set_at(["git", "url"], "ftp://x/y"), "git.url"),
        (set_at(["git", "url"], "http://git.example.com/a.git"), "git.url"),
        (set_at(["git", "url"], "file:///srv/repo"), "development only"),
        (set_at(["git", "url"], "ssh://git:pw@git.example.com/a.git"), "credentials"),
        (set_at(["git", "checkout_dir"], "/etc"), "relative to the state"),
        (set_at(["git", "checkout_dir"], "../x"), "relative to the state"),
        (set_at(["git", "checkout_dir"], "."), "inside the state"),
        (set_at(["git", "url"], "-oProxyCommand=x"), "git.url"),
        (set_at(["git", "url"], "https://user:pw@git.example.com/x.git"), "credentials"),
        (set_at(["git", "branch"], "--upload-pack=x"), "branch"),
        (set_at(["git", "branch"], "a..b"), "branch"),
        (set_at(["git", "verify_ssl"], "no"), "verify_ssl"),
        (set_at(["git", "auth"], {"type": "kerberos"}), "auth.type"),
        (set_at(["git", "auth"], {"type": "token", "token_env": "bad name"}), "token_env"),
        (set_at(["git", "auth"], {"type": "none", "x": 1}), "unknown key"),
        (set_at(["git", "bogus"], 1), "unknown key"),
        (set_at(["source", "directory"], "../etc"), "relative"),
        (set_at(["source", "directory"], "/etc"), "relative"),
        (set_at(["source", "filename_pattern"], "../*.csv"), "relative pattern"),
        (set_at(["source", "csv_delimiter"], "#"), "csv_delimiter"),
        (set_at(["mapping"], []), "list of"),
        (set_at(["bogus"], 1), "top-level"),
    ],
)
def test_invalid_configs_are_refused(mutate, message):
    with pytest.raises(DataConfigError, match=message):
        parse(mutate)


def test_a_missing_git_section_and_a_non_mapping_file_are_refused():
    with pytest.raises(DataConfigError, match="git: section is required"):
        parse_data_config({"mapping": []}, ENV)
    with pytest.raises(DataConfigError, match="mapping"):
        parse_data_config(["x"], ENV)


def test_a_relative_key_path_is_refused():
    def use_key(raw):
        raw["git"]["auth"] = {"type": "ssh", "key_file": "-o"}

    with pytest.raises(DataConfigError, match="absolute"):
        parse(use_key)


def test_token_needs_https():
    def mutate(raw):
        raw["git"]["url"] = "ssh://git@git.example.com/a.git"
        raw["git"]["auth"] = {"type": "token", "token_env": "GIT_TOKEN"}

    with pytest.raises(DataConfigError, match="needs an https"):
        parse(mutate)


def test_ssh_url_with_a_user_but_no_password_is_fine():
    def mutate(raw):
        raw["git"]["url"] = "ssh://git@git.example.com/a.git"

    assert parse(mutate).git.url.startswith("ssh://git@")


def test_file_urls_need_the_development_switch():
    def mutate(raw):
        raw["git"]["url"] = "file:///srv/repo"

    env = {**ENV, "MANUS_AGENT_ALLOW_FILE_URLS": "1"}
    assert parse(mutate, env=env).git.url == "file:///srv/repo"


def test_the_checkout_lives_under_the_state_directory(tmp_path):
    env = {"MANUS_AGENT_STATE_DIR": str(tmp_path)}
    config = parse(set_at(["git", "checkout_dir"], "a/b"), env=env)
    assert config.git.checkout_dir == tmp_path.resolve() / "a" / "b"
    assert config.git.state_dir == tmp_path.resolve()


def test_a_checkout_symlink_leaving_the_state_directory_is_refused(tmp_path):
    state = tmp_path / "state"
    state.mkdir()
    (state / "repo").symlink_to(tmp_path)
    with pytest.raises(DataConfigError, match="inside the state"):
        parse(env={"MANUS_AGENT_STATE_DIR": str(state)})


def test_scp_style_urls_and_tab_delimiter_are_accepted():
    def mutate(raw):
        raw["git"]["url"] = "git@git.example.com:org/ips.git"
        raw["source"]["csv_delimiter"] = "\\t"

    config = parse(mutate)
    assert config.source.csv_delimiter == "\t"


def test_load_reads_yaml_and_reports_unreadable_or_invalid_files(tmp_path):
    good = tmp_path / "config.yaml"
    good.write_text(
        "git:\n  url: https://git.example.com/a.git\n"
        "mapping:\n"
        "  - {source: name, target: name}\n"
        "  - {source: nic, target: interfaces.name}\n"
    )
    assert load_data_config(good, {}).source.filename_pattern == "*.csv"
    with pytest.raises(DataConfigError, match="cannot read"):
        load_data_config(tmp_path / "missing.yaml", {})
    bad = tmp_path / "bad.yaml"
    bad.write_text("git: [unclosed")
    with pytest.raises(DataConfigError, match="not valid YAML"):
        load_data_config(bad, {})
