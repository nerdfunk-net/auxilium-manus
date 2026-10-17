"""Git version control operations: branches, commits, diffs."""

from __future__ import annotations

import difflib
import logging
from typing import Any

from git import GitCommandError
from git.exc import BadName

from core.domain_exceptions import ValidationFailedError
from services.git.shared_utils import get_git_repo_by_id

logger = logging.getLogger(__name__)

_CACHE_CFG = {"enabled": True, "ttl_seconds": 600, "max_commits": 500}

# At most this much of one file side is read for a comparison.
MAX_COMPARE_BYTES = 1024 * 1024


def _read_side(commit: Any, file_path: str) -> str:
    """One side of a comparison; a file that is absent in the commit reads as empty."""
    try:
        blob = commit.tree / file_path
    except KeyError:
        return ""
    data = blob.data_stream.read(MAX_COMPARE_BYTES + 1)
    if len(data) > MAX_COMPARE_BYTES:
        raise ValidationFailedError("file is too large to compare (more than 1 MiB)")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValidationFailedError("binary or non-UTF-8 file cannot be compared") from exc


class GitVersionControlService:
    """Encapsulates VCS operations: branch listing, commit log, and diff computation."""

    def get_commits(
        self,
        repo_id: int,
        branch_name: str,
        cache_service=None,
    ) -> list[dict[str, Any]]:
        """Return commits for a branch, using cache when available."""
        repo = get_git_repo_by_id(repo_id)

        if branch_name not in [ref.name for ref in repo.refs]:
            raise ValueError(f"Branch '{branch_name}' not found")

        cache_key = f"repo:{repo_id}:commits:{branch_name}"
        if _CACHE_CFG.get("enabled", True) and cache_service:
            cached = cache_service.get(cache_key)
            if cached is not None:
                return cached

        limit = int(_CACHE_CFG.get("max_commits", 500))
        commits = [
            {
                "hash": commit.hexsha,
                "short_hash": commit.hexsha[:8],
                "message": commit.message.strip(),
                "author": {"name": commit.author.name, "email": commit.author.email},
                "date": commit.committed_datetime.isoformat(),
                "files_changed": len(commit.stats.files),
            }
            for commit in repo.iter_commits(branch_name, max_count=limit)
        ]

        if _CACHE_CFG.get("enabled", True) and cache_service:
            cache_service.set(cache_key, commits, int(_CACHE_CFG.get("ttl_seconds", 600)))

        return commits

    def compare_commits(
        self,
        repo_id: int,
        commit1: str,
        commit2: str,
        file_path: str,
    ) -> dict[str, Any]:
        """Compare a file between two commits and return unified diff + side-by-side data."""
        repo = get_git_repo_by_id(repo_id)

        try:
            commit_obj1 = repo.commit(commit1)
            commit_obj2 = repo.commit(commit2)
        except (BadName, ValueError, GitCommandError) as exc:
            raise ValidationFailedError("unknown revision") from exc

        file_content1 = _read_side(commit_obj1, file_path)
        file_content2 = _read_side(commit_obj2, file_path)

        lines1 = file_content1.splitlines(keepends=True)
        lines2 = file_content2.splitlines(keepends=True)

        diff_lines = [line.rstrip("\n") for line in difflib.unified_diff(lines1, lines2, n=3)]

        additions = sum(1 for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++"))
        deletions = sum(1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---"))

        lines1_list = file_content1.splitlines()
        lines2_list = file_content2.splitlines()

        file1_lines: list[dict] = []
        file2_lines: list[dict] = []

        matcher = difflib.SequenceMatcher(None, lines1_list, lines2_list)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                file1_lines += [
                    {"line_number": i + 1, "content": lines1_list[i], "type": "equal"}
                    for i in range(i1, i2)
                ]
                file2_lines += [
                    {"line_number": j + 1, "content": lines2_list[j], "type": "equal"}
                    for j in range(j1, j2)
                ]
            elif tag == "delete":
                file1_lines += [
                    {"line_number": i + 1, "content": lines1_list[i], "type": "delete"}
                    for i in range(i1, i2)
                ]
            elif tag == "insert":
                file2_lines += [
                    {"line_number": j + 1, "content": lines2_list[j], "type": "insert"}
                    for j in range(j1, j2)
                ]
            elif tag == "replace":
                file1_lines += [
                    {"line_number": i + 1, "content": lines1_list[i], "type": "replace"}
                    for i in range(i1, i2)
                ]
                file2_lines += [
                    {"line_number": j + 1, "content": lines2_list[j], "type": "replace"}
                    for j in range(j1, j2)
                ]

        return {
            "commit1": commit1[:8],
            "commit2": commit2[:8],
            "file_path": file_path,
            "diff_lines": diff_lines,
            "left_file": f"{file_path} ({commit1[:8]})",
            "right_file": f"{file_path} ({commit2[:8]})",
            "left_lines": file1_lines,
            "right_lines": file2_lines,
            "stats": {
                "additions": additions,
                "deletions": deletions,
                "changes": additions + deletions,
                "total_lines": len(diff_lines),
            },
        }
