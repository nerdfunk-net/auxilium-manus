"""Helpers to build real throwaway git repositories for unit tests.

Not a test module (leading underscore); imported by the ``test_git_*`` suites
that exercise ``services/git/*`` against real repos instead of mocks.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_ENV = {
    "GIT_AUTHOR_NAME": "Test Author",
    "GIT_AUTHOR_EMAIL": "author@test.local",
    "GIT_COMMITTER_NAME": "Test Committer",
    "GIT_COMMITTER_EMAIL": "committer@test.local",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


def git(*args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    """Run a git command in *cwd*, raising on non-zero exit."""
    import os

    env = {**os.environ, **_ENV}
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def make_working_repo(root: Path, name: str = "work") -> Path:
    """Create a git repo at ``root/name`` with two commits on ``main``.

    Files: ``README.md`` (2 commits), ``config/router1.cfg`` (1 commit),
    ``data.bin`` (binary, 1 commit).
    """
    repo = root / name
    repo.mkdir(parents=True)
    git("init", "-b", "main", cwd=repo)
    git("config", "user.email", "committer@test.local", cwd=repo)
    git("config", "user.name", "Test Committer", cwd=repo)

    (repo / "README.md").write_text("hello world\n")
    (repo / "config").mkdir()
    (repo / "config" / "router1.cfg").write_text("hostname router1\n")
    (repo / "data.bin").write_bytes(b"\x00\x01\x02\x03\xff\xfe")
    git("add", "-A", cwd=repo)
    git("commit", "-m", "initial commit", cwd=repo)

    (repo / "README.md").write_text("hello world\nsecond line\n")
    git("add", "-A", cwd=repo)
    git("commit", "-m", "update readme", cwd=repo)

    return repo


def make_repo_with_remote(root: Path) -> tuple[Path, Path]:
    """Create a bare ``remote.git`` and a working clone wired to it.

    Returns ``(working_repo, bare_remote)``. The working repo has one commit
    pushed to the remote's ``main`` branch.
    """
    bare = root / "remote.git"
    git("init", "--bare", "-b", "main", str(bare), cwd=root)

    work = root / "work"
    git("clone", f"file://{bare}", str(work), cwd=root)
    git("config", "user.email", "committer@test.local", cwd=work)
    git("config", "user.name", "Test Committer", cwd=work)
    (work / "README.md").write_text("hello\n")
    git("add", "-A", cwd=work)
    git("commit", "-m", "initial commit", cwd=work)
    git("push", "origin", "main", cwd=work)

    return work, bare
