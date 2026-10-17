"""S4-03: branch names must never be parseable as git options."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

from models.git_repositories import GitConnectionTestRequest, GitRepositoryRequest
from services.git.cache import GitCacheService
from services.git.refs import validate_branch_name

HOSTILE = [
    "--output=/tmp/pwn",
    "-x",
    "--upload-pack=x",
    "a..b",
    "a@{u}",
    "a/",
    "x.lock",
    "a b",
    "//x",
    "a" * 256,
    "",
]


@pytest.mark.parametrize("name", HOSTILE)
def test_hostile_branch_names_rejected(name: str) -> None:
    with pytest.raises(ValueError):
        validate_branch_name(name)


@pytest.mark.parametrize("name", ["main", "feature/x-1", "release-1.2", "manus/cr-5"])
def test_normal_branch_names_accepted(name: str) -> None:
    assert validate_branch_name(name) == name


def test_repository_request_rejects_option_branch() -> None:
    with pytest.raises(ValidationError):
        GitRepositoryRequest(
            name="r",
            category="device_configs",
            url="https://example.com/r.git",
            branch="--output=/x",
        )
    with pytest.raises(ValidationError):
        GitConnectionTestRequest(url="https://example.com/r.git", branch="-x")


def test_git_cache_fallback_cannot_overwrite_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    victim = tmp_path / "victim.py"
    victim.write_text("print('original')")
    service = GitCacheService(MagicMock())
    result = service._fetch_commits_subprocess(str(repo), f"--output={victim}", 5)
    assert victim.read_text() == "print('original')"
    assert result == []
