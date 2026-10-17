"""S3-01: the git token never reaches argv, the remote URL or .git/config."""

from __future__ import annotations

import base64
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from git import Repo

from services.git.auth import strip_http_userinfo
from services.git.env import build_git_env_overrides
from services.git.service import GitService

REPO = {
    "id": 1,
    "name": "creds-test",
    "url": "https://git.example.com/org/x.git",
    "branch": "main",
    "auth_type": "token",
}


def _auth_cm(service: GitService, token: str = "TOKEN-1234"):
    cm = MagicMock()
    cm.__enter__.return_value = (REPO["url"], "svc", token, None)
    cm.__exit__.return_value = False
    service._auth = MagicMock()
    service._auth.setup_auth_environment.return_value = cm
    service._auth.normalize_url.side_effect = lambda u: u
    return service


def test_env_carries_header_not_url() -> None:
    env = build_git_env_overrides(REPO, username="svc", token="TOKEN-1234")
    assert env["GIT_CONFIG_KEY_0"] == "http.followRedirects"
    assert env["GIT_CONFIG_KEY_1"] == "http.https://git.example.com/.extraHeader"
    expected = "Authorization: Basic " + base64.b64encode(b"svc:TOKEN-1234").decode()
    assert env["GIT_CONFIG_VALUE_1"] == expected
    assert env["GIT_CONFIG_COUNT"] == "2"


def test_no_token_means_no_header() -> None:
    env = build_git_env_overrides(REPO)
    assert env["GIT_CONFIG_COUNT"] == "1"


def test_ssh_key_auth_has_no_header() -> None:
    env = build_git_env_overrides(REPO, ssh_key_path="/k", token="T")
    assert not any("extraHeader" in v for k, v in env.items() if k.startswith("GIT_CONFIG_KEY"))


def test_clone_uses_clean_url_and_header_env(tmp_path: Path) -> None:
    service = _auth_cm(GitService())
    with (
        patch("services.git.service.validate_git_remote_url"),
        patch("services.git.service.Repo.clone_from") as clone,
    ):
        service._clone_fresh(REPO, tmp_path / "wt")
    args, kwargs = clone.call_args
    assert "@" not in args[0]
    assert "TOKEN-1234" not in args[0]
    assert kwargs["env"]["GIT_CONFIG_KEY_1"] == "http.https://git.example.com/.extraHeader"


def test_pull_and_push_never_call_set_url() -> None:
    service = _auth_cm(GitService())
    repo = MagicMock()
    repo.head.is_valid.return_value = False
    with patch("services.git.service.validate_git_remote_url"):
        service.pull(REPO, repo=repo)
        service.push(REPO, repo=repo)
        service.fetch(REPO, repo=repo)
    repo.remotes.origin.set_url.assert_not_called()
    assert repo.remotes.origin.pull.called
    assert repo.remotes.origin.fetch.called


def test_open_or_clone_scrubs_token_from_existing_config(tmp_path: Path) -> None:
    wt = tmp_path / "wt"
    wt.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=wt, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", "https://svc:TOKEN-1234@git.example.com/org/x.git"],
        cwd=wt,
        check=True,
    )
    service = GitService()
    service._auth = MagicMock()
    service._auth.normalize_url.side_effect = lambda u: strip_http_userinfo(u)
    with (
        patch("services.git.service.validate_git_remote_url"),
        patch.object(GitService, "get_repo_path", return_value=wt),
    ):
        Repo(wt)  # sanity
        service.open_or_clone(REPO)
    assert "TOKEN-1234" not in (wt / ".git" / "config").read_text()


def test_strip_http_userinfo_leaves_ssh_alone() -> None:
    assert strip_http_userinfo("ssh://git@host/x.git") == "ssh://git@host/x.git"
    assert strip_http_userinfo("git@host:x.git") == "git@host:x.git"
    assert strip_http_userinfo("https://u:p@host/x.git") == "https://host/x.git"
