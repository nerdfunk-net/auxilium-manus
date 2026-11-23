"""Tests for services.git.commit_info.last_commit_of (real temporary git repositories)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from git import Repo
from git.exc import InvalidGitRepositoryError

from services.git.commit_info import LastCommit, last_commit_of


def _commit(repo: Repo, relative: str, text: str, when: datetime) -> str:
    path = Path(repo.working_tree_dir) / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    repo.index.add([relative])
    stamp = f"{int(when.timestamp())} +0000"
    commit = repo.index.commit(f"update {relative}", author_date=stamp, commit_date=stamp)
    return commit.hexsha


@pytest.fixture
def repo(tmp_path: Path) -> Repo:
    return Repo.init(tmp_path)


def test_returns_the_newest_commit_touching_the_path(repo: Repo, tmp_path: Path) -> None:
    _commit(repo, "r1.cfg", "a", datetime(2026, 1, 1, tzinfo=UTC))
    newest = _commit(repo, "r1.cfg", "b", datetime(2026, 2, 1, tzinfo=UTC))
    _commit(repo, "r2.cfg", "x", datetime(2026, 3, 1, tzinfo=UTC))

    result = last_commit_of(tmp_path, "r1.cfg")

    assert result == LastCommit(sha=newest, committed_at=datetime(2026, 2, 1, tzinfo=UTC))


def test_path_in_subdirectory(repo: Repo, tmp_path: Path) -> None:
    sha = _commit(repo, "DC1/r1.cfg", "a", datetime(2026, 1, 5, tzinfo=UTC))

    result = last_commit_of(tmp_path, "DC1/r1.cfg")

    assert result is not None and result.sha == sha


def test_untracked_file_has_no_commit(repo: Repo, tmp_path: Path) -> None:
    _commit(repo, "other.cfg", "a", datetime(2026, 1, 1, tzinfo=UTC))
    (tmp_path / "new.cfg").write_text("x", encoding="utf-8")

    assert last_commit_of(tmp_path, "new.cfg") is None


def test_brackets_in_the_path_are_literal_not_a_glob(repo: Repo, tmp_path: Path) -> None:
    # "DC[1]/r.cfg" as a git pathspec is a character class that also matches "DC1/r.cfg".
    literal = _commit(repo, "DC[1]/r.cfg", "old", datetime(2026, 1, 1, tzinfo=UTC))
    _commit(repo, "DC1/r.cfg", "new", datetime(2026, 11, 1, tzinfo=UTC))

    result = last_commit_of(tmp_path, "DC[1]/r.cfg")

    assert result == LastCommit(sha=literal, committed_at=datetime(2026, 1, 1, tzinfo=UTC))


def test_other_pathspec_characters_stay_literal(repo: Repo, tmp_path: Path) -> None:
    wanted = _commit(repo, "a{b}.cfg", "x", datetime(2026, 1, 1, tzinfo=UTC))
    _commit(repo, "ab.cfg", "y", datetime(2026, 11, 1, tzinfo=UTC))

    result = last_commit_of(tmp_path, "a{b}.cfg")

    assert result is not None and result.sha == wanted


def test_not_a_repository_raises(tmp_path: Path) -> None:
    with pytest.raises(InvalidGitRepositoryError):
        last_commit_of(tmp_path, "r1.cfg")
