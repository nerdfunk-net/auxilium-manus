"""Git version control operations: branches, commits, diffs."""

from __future__ import annotations

import difflib
import logging
from typing import Any

from services.git.shared_utils import get_git_repo_by_id

logger = logging.getLogger(__name__)

_CACHE_CFG = {"enabled": True, "ttl_seconds": 600, "max_commits": 500}


class GitVersionControlService:
    """Encapsulates VCS operations: branch listing, commit log, and diff computation."""

    def get_branches(self, repo_id: int) -> list[dict[str, Any]]:
        """Return all branches with a flag indicating which is active."""
        repo = get_git_repo_by_id(repo_id)
        current_branch = repo.active_branch.name if repo.active_branch else None
        return [
            {"name": branch.name, "current": branch.name == current_branch}
            for branch in repo.branches
        ]

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

        commit_obj1 = repo.commit(commit1)
        commit_obj2 = repo.commit(commit2)

        try:
            file_content1 = (commit_obj1.tree / file_path).data_stream.read().decode("utf-8")
        except KeyError:
            file_content1 = ""

        try:
            file_content2 = (commit_obj2.tree / file_path).data_stream.read().decode("utf-8")
        except KeyError:
            file_content2 = ""

        lines1 = file_content1.splitlines(keepends=True)
        lines2 = file_content2.splitlines(keepends=True)

        diff_lines = [
            line.rstrip("\n")
            for line in difflib.unified_diff(lines1, lines2, n=3)
        ]

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
