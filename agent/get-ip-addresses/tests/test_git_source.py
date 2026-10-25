import os
import shlex
import subprocess

import pytest

from manus_agent.data_config import GitAuth, GitSettings
from manus_agent.git_source import (
    GitSourceError,
    _git_env,
    list_source_files,
    scrub,
    sync_repository,
)
from tests.data_helpers import SAMPLE_CSV, commit, make_origin


def settings(origin, checkout, **overrides):
    values = {
        "url": f"file://{origin}",
        "branch": "main",
        "auth": GitAuth(),
        "verify_ssl": True,
        "checkout_dir": checkout,
        "state_dir": checkout.parent,
    }
    values.update(overrides)
    return GitSettings(**values)


def test_first_start_clones_and_a_restart_pulls_new_commits(tmp_path):
    origin = make_origin(tmp_path)
    git = settings(origin, tmp_path / "data" / "repo")
    checkout = sync_repository(git, {})
    assert (checkout / "ips" / "devices.csv").read_text() == SAMPLE_CSV

    more = SAMPLE_CSV + "device-2;e0;10.1.1.1/24;true;Global\n"
    commit(origin, {"ips/devices.csv": more}, "more")
    sync_repository(git, {})
    assert "device-2" in (checkout / "ips" / "devices.csv").read_text()


def test_a_restart_discards_local_changes_in_the_checkout(tmp_path):
    origin = make_origin(tmp_path)
    git = settings(origin, tmp_path / "repo")
    checkout = sync_repository(git, {})
    (checkout / "ips" / "devices.csv").write_text("tampered")
    (checkout / "ips" / "stray.csv").write_text("x")
    sync_repository(git, {})
    assert (checkout / "ips" / "devices.csv").read_text() == SAMPLE_CSV
    assert not (checkout / "ips" / "stray.csv").exists()


def test_a_missing_branch_fails_with_a_git_source_error(tmp_path):
    origin = make_origin(tmp_path)
    with pytest.raises(GitSourceError, match="git clone failed"):
        sync_repository(settings(origin, tmp_path / "repo", branch="nope"), {})


def test_an_unreachable_repository_fails(tmp_path):
    with pytest.raises(GitSourceError, match="failed"):
        sync_repository(settings(tmp_path / "missing", tmp_path / "repo"), {})


def test_a_missing_git_executable_is_reported(tmp_path):
    def runner(*args, **kwargs):
        raise FileNotFoundError

    with pytest.raises(GitSourceError, match="not found"):
        sync_repository(settings(tmp_path, tmp_path / "r"), {}, runner=runner)


def test_a_timeout_is_reported(tmp_path):
    def runner(*args, **kwargs):
        raise subprocess.TimeoutExpired("git", 1)

    with pytest.raises(GitSourceError, match="timed out"):
        sync_repository(settings(tmp_path, tmp_path / "r"), {}, runner=runner)


def test_the_token_is_in_the_child_environment_only_and_scrubbed_from_errors(tmp_path):
    seen = {}

    def runner(args, **kwargs):
        seen["args"] = args
        seen["env"] = kwargs["env"]
        raise subprocess.CalledProcessError(
            128, args, stderr="fatal: Authorization: Basic X failed for s3cret-token"
        )

    git = settings(
        tmp_path,
        tmp_path / "r",
        auth=GitAuth("token", username="u", token_env="TOK"),
        verify_ssl=False,
    )
    with pytest.raises(GitSourceError) as caught:
        env = {"TOK": "s3cret-token", "PATH": "/usr/bin", "SECRET_OTHER": "z"}
        sync_repository(git, env, runner=runner)
    assert "s3cret-token" not in str(caught.value)
    assert not any("s3cret-token" in part for part in seen["args"])
    assert seen["env"]["GIT_CONFIG_COUNT"] == "3"
    assert "SECRET_OTHER" not in seen["env"]
    assert seen["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_ssh_auth_sets_a_quoted_command_with_known_hosts_in_the_state_directory(tmp_path):
    key = tmp_path / "id"
    state = tmp_path / "state"
    git = settings(tmp_path, state / "repo", auth=GitAuth("ssh", key_file=key))
    env, secrets = _git_env(git, {"PATH": "/bin"})
    command = shlex.split(env["GIT_SSH_COMMAND"])
    assert command[:3] == ["ssh", "-i", str(key)]
    assert "BatchMode=yes" in command
    assert f"UserKnownHostsFile={state / 'known_hosts'}" in command
    assert secrets == ()


def test_a_path_with_shell_characters_stays_one_argument_even_if_it_got_through(tmp_path):
    key = tmp_path / "k; touch pwned -o ProxyCommand=x"
    env, _ = _git_env(
        settings(tmp_path, tmp_path / "s" / "r", auth=GitAuth("ssh", key_file=key)), {}
    )
    command = shlex.split(env["GIT_SSH_COMMAND"])
    assert command[2] == str(key)
    assert not any(part.startswith("ProxyCommand") for part in command)


def test_the_token_header_is_scoped_to_the_configured_origin(tmp_path):
    git = settings(
        tmp_path,
        tmp_path / "s" / "r",
        url="https://git.example.com:8443/org/r.git",
        auth=GitAuth("token", username="u", token_env="TOK"),
    )
    env, _ = _git_env(git, {"TOK": "t", "PATH": os.environ["PATH"]})
    keys = [env[f"GIT_CONFIG_KEY_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))]
    assert "http.https://git.example.com:8443/.extraHeader" in keys
    assert "http.extraHeader" not in keys
    assert "http.followRedirects" in keys
    # git itself agrees: the header is offered to that origin and to no other host
    probe = {**env, "HOME": str(tmp_path)}
    for host, expected in (("git.example.com:8443", 0), ("evil.example.org", 1)):
        result = subprocess.run(  # noqa: S603
            ["git", "config", "--get-urlmatch", "http.extraHeader", f"https://{host}/org/r.git"],  # noqa: S607
            env=probe,
            capture_output=True,
        )
        assert result.returncode == expected, host


def test_redirects_are_not_followed(tmp_path):
    env, _ = _git_env(settings(tmp_path, tmp_path / "s" / "r"), {})
    index = [env[f"GIT_CONFIG_KEY_{i}"] for i in range(int(env["GIT_CONFIG_COUNT"]))].index(
        "http.followRedirects"
    )
    assert env[f"GIT_CONFIG_VALUE_{index}"] == "false"


def test_turning_tls_verification_off_is_logged(tmp_path, caplog):
    with caplog.at_level("WARNING"):
        env, _ = _git_env(settings(tmp_path, tmp_path / "s" / "r", verify_ssl=False), {})
    assert "verification is turned off" in caplog.text
    assert "false" in env.values()


def test_scrub_removes_url_credentials_and_secrets():
    text = "fatal: https://user:pw@host/x.git and tok123"
    assert scrub(text, ("tok123",)) == "fatal: https://***@host/x.git and ***"


def test_list_source_files(tmp_path):
    root = tmp_path / "co"
    (root / "ips").mkdir(parents=True)
    (root / "ips" / "b.csv").write_text("x")
    (root / "ips" / "a.csv").write_text("x")
    (root / "ips" / "note.txt").write_text("x")
    (root / "ips" / "dir.csv").mkdir()
    (root / ".git").mkdir()
    (root / ".git" / "c.csv").write_text("x")
    names = [p.name for p in list_source_files(root, "ips", "*.csv")]
    assert names == ["a.csv", "b.csv"]
    assert [p.name for p in list_source_files(root, "", "ips/*.csv")] == ["a.csv", "b.csv"]


def test_directory_must_exist_and_stay_inside(tmp_path):
    root = tmp_path / "co"
    root.mkdir()
    with pytest.raises(GitSourceError, match="does not exist"):
        list_source_files(root, "nope", "*.csv")
    with pytest.raises(GitSourceError, match="outside"):
        list_source_files(root, "../", "*.csv")


def test_a_symlink_out_of_the_checkout_is_not_read(tmp_path):
    root = tmp_path / "co"
    root.mkdir()
    outside = tmp_path / "secret.csv"
    outside.write_text("x")
    (root / "link.csv").symlink_to(outside)
    assert list_source_files(root, "", "*.csv") == []
