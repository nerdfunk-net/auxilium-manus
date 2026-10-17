"""Read-only inspection of a repository's working tree and its sync with origin.

Used by the ``git-status`` workflow step. The only side effect is an optional
``git fetch`` (via ``GitService.fetch``, which enforces URL safety and auth).
"""

from __future__ import annotations

import logging
from typing import Any

from git import Repo

logger = logging.getLogger(__name__)

MAX_LISTED_FILES = 100

REASON_UNCOMMITTED = "uncommitted_changes"
REASON_UNTRACKED = "untracked_files"
REASON_AHEAD = "ahead_of_origin"
REASON_BEHIND = "behind_origin"
REASON_BRANCH_MISMATCH = "branch_mismatch"
REASON_NO_REMOTE_BRANCH = "no_remote_branch"


def _capped(paths: list[str]) -> list[str]:
    return sorted(paths)[:MAX_LISTED_FILES]


def _current_branch(repo: Repo) -> str | None:
    try:
        return repo.active_branch.name
    except TypeError:  # detached HEAD
        return None


def _changed_paths(repo: Repo) -> tuple[list[str], list[str]]:
    """Return (unstaged, staged) changed paths."""
    unstaged = [path for d in repo.index.diff(None) if (path := d.b_path or d.a_path)]
    staged = (
        [path for d in repo.index.diff("HEAD") if (path := d.b_path or d.a_path)]
        if repo.head.is_valid()
        else []
    )
    return unstaged, staged


def _sync_counts(repo: Repo, branch: str) -> tuple[int, int] | None:
    """Return (ahead, behind) vs ``origin/<branch>``, or None if that ref is missing."""
    remote_ref = f"origin/{branch}"
    if remote_ref not in [ref.name for ref in repo.refs]:
        return None
    ahead = sum(1 for _ in repo.iter_commits(f"{remote_ref}..HEAD"))
    behind = sum(1 for _ in repo.iter_commits(f"HEAD..{remote_ref}"))
    return ahead, behind


def collect_status(
    git_service: Any,
    repository: dict[str, Any],
    *,
    fetch: bool = True,
    check_uncommitted: bool = True,
    check_untracked: bool = True,
    check_sync: bool = True,
) -> dict[str, Any]:
    """Inspect the repository's working tree and compare it to origin.

    Raises ``RuntimeError`` if the requested fetch fails. ``reasons`` holds stable
    codes explaining why ``clean`` is False; disabled checks never add a reason.
    """
    repo = git_service.open_or_clone(repository)
    configured_branch = repository.get("branch", "main")

    if fetch and check_sync:
        result = git_service.fetch(repository, repo=repo)
        if not result.success:
            raise result.error()

    branch = _current_branch(repo)
    unstaged, staged = _changed_paths(repo)
    untracked = list(repo.untracked_files)
    head_commit = repo.head.commit.hexsha if repo.head.is_valid() else None

    reasons: list[str] = []
    ahead_count = 0
    behind_count = 0

    if check_uncommitted and (unstaged or staged):
        reasons.append(REASON_UNCOMMITTED)
    if check_untracked and untracked:
        reasons.append(REASON_UNTRACKED)

    if check_sync:
        if branch != configured_branch:
            reasons.append(REASON_BRANCH_MISMATCH)
        counts = _sync_counts(repo, branch or configured_branch)
        if counts is None:
            reasons.append(REASON_NO_REMOTE_BRANCH)
        else:
            ahead_count, behind_count = counts
            if ahead_count:
                reasons.append(REASON_AHEAD)
            if behind_count:
                reasons.append(REASON_BEHIND)

    return {
        "clean": not reasons,
        "reasons": reasons,
        "checks": {
            "uncommitted": check_uncommitted,
            "untracked": check_untracked,
            "sync": check_sync,
        },
        "branch": branch,
        "expected_branch": configured_branch,
        "head_commit": head_commit,
        "fetched": fetch and check_sync,
        "ahead_count": ahead_count,
        "behind_count": behind_count,
        "modified_count": len(set(unstaged)),
        "staged_count": len(set(staged)),
        "untracked_count": len(untracked),
        "modified_files": _capped(list(set(unstaged))),
        "staged_files": _capped(list(set(staged))),
        "untracked_files": _capped(untracked),
        "truncated": any(
            len(paths) > MAX_LISTED_FILES for paths in (set(unstaged), set(staged), untracked)
        ),
    }
