"""The newest commit that touched one file of a checked-out repository.

Shared by the Ask the Net config-backup reader and the ``get-age-of-backup`` step. A repository
only records a commit when a file's content changed, so this is "when the file last changed",
never "when it was last written".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from git import Repo

# Git pathspec magic: no glob, no character class, no further magic in what follows.
_LITERAL_PATHSPEC = ":(literal)"


@dataclass(frozen=True)
class LastCommit:
    sha: str
    committed_at: datetime  # timezone-aware, UTC


def last_commit_of(root: Path, relative: str) -> LastCommit | None:
    """The newest commit touching *relative* below *root*; ``None`` when the file has no commit.

    The path is passed to git as a *literal* pathspec: a plain pathspec treats ``[`` and ``]`` as
    a character class, so ``DC[1]/r.cfg`` would also match (and report the commit of) ``DC1/r.cfg``.

    Blocking (reads the git history): call it from a worker thread. A directory that is not a
    repository, or a history that cannot be read, raises the GitPython error.
    """
    repo = Repo(root)
    try:
        commit = next(repo.iter_commits(paths=f"{_LITERAL_PATHSPEC}{relative}", max_count=1), None)
    finally:
        repo.close()
    if commit is None:
        return None
    return LastCommit(
        sha=commit.hexsha,
        committed_at=datetime.fromtimestamp(commit.committed_date, UTC),
    )
