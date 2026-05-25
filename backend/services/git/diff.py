"""
Git Diff Service - Centralized diff operations.

This service consolidates all diff calculation logic that was previously
duplicated across git_version_control.py and git_compare.py.
"""

from __future__ import annotations

import difflib
import logging
from typing import List, Tuple

from git import Repo

from models.git import DiffLine, DiffResult, DiffStats

logger = logging.getLogger(__name__)


class GitDiffService:
    """Service for performing git diff operations."""

    def unified_diff(
        self, lines1: List[str], lines2: List[str], n: int = 3
    ) -> List[str]:
        """Generate unified diff between two sets of lines.

        Args:
            lines1: Lines from first version
            lines2: Lines from second version
            n: Number of context lines (default: 3)

        Returns:
            List of unified diff lines
        """
        diff_lines = []
        for line in difflib.unified_diff(lines1, lines2, n=n):
            diff_lines.append(line.rstrip("\n"))
        return diff_lines

    def calculate_diff_stats(self, diff_lines: List[str]) -> DiffStats:
        """Calculate statistics from unified diff lines.

        Args:
            diff_lines: List of unified diff lines

        Returns:
            DiffStats with additions and deletions count
        """
        additions = sum(
            1
            for line in diff_lines
            if line.startswith("+") and not line.startswith("+++")
        )
        deletions = sum(
            1
            for line in diff_lines
            if line.startswith("-") and not line.startswith("---")
        )

        return DiffStats(additions=additions, deletions=deletions)

    def line_by_line_diff(
        self, content1: str, content2: str
    ) -> Tuple[List[DiffLine], DiffStats]:
        """Generate line-by-line diff with metadata.

        Args:
            content1: First file content
            content2: Second file content

        Returns:
            Tuple of (list of DiffLine objects, DiffStats)
        """
        lines1 = content1.splitlines(keepends=True)
        lines2 = content2.splitlines(keepends=True)

        diff_lines = self.unified_diff(lines1, lines2)
        stats = self.calculate_diff_stats(diff_lines)

        # Parse diff lines into structured format
        parsed_lines: List[DiffLine] = []
        line_number = 0

        for line in diff_lines:
            if line.startswith("@@"):
                # Parse hunk header to get line numbers
                # Format: @@ -old_start,old_count +new_start,new_count @@
                continue
            elif line.startswith("+++") or line.startswith("---"):
                # Skip file headers
                continue
            elif line.startswith("+"):
                line_number += 1
                parsed_lines.append(
                    DiffLine(line_number=line_number, type="add", content=line[1:])
                )
            elif line.startswith("-"):
                line_number += 1
                parsed_lines.append(
                    DiffLine(line_number=line_number, type="remove", content=line[1:])
                )
            else:
                line_number += 1
                parsed_lines.append(
                    DiffLine(
                        line_number=line_number,
                        type="context",
                        content=line[1:] if line.startswith(" ") else line,
                    )
                )

        return parsed_lines, stats

    def compare_file_versions(
        self, repo: Repo, file_path: str, commit1: str, commit2: str
    ) -> DiffResult:
        """Compare a file between two commits in the same repository.

        Args:
            repo: GitPython Repo instance
            file_path: Path to file within repository
            commit1: First commit hash
            commit2: Second commit hash

        Returns:
            DiffResult with unified diff, line-by-line diff, and stats
        """
        try:
            # Get file content from both commits
            commit1_obj = repo.commit(commit1)
            commit2_obj = repo.commit(commit2)

            try:
                content1 = (
                    commit1_obj.tree[file_path].data_stream.read().decode("utf-8")
                )
            except KeyError:
                content1 = ""
                logger.warning("File %s not found in commit %s", file_path, commit1)

            try:
                content2 = (
                    commit2_obj.tree[file_path].data_stream.read().decode("utf-8")
                )
            except KeyError:
                content2 = ""
                logger.warning("File %s not found in commit %s", file_path, commit2)

            # Generate diff
            lines1 = content1.splitlines(keepends=True)
            lines2 = content2.splitlines(keepends=True)

            diff_lines = self.unified_diff(lines1, lines2)
            line_by_line, stats = self.line_by_line_diff(content1, content2)

            return DiffResult(
                diff_lines=diff_lines, line_by_line=line_by_line, stats=stats
            )

        except Exception as e:
            logger.error("Error comparing file versions: %s", e)
            raise

    def compare_files_across_repos(
        self,
        repo1: Repo,
        repo2: Repo,
        file_path: str,
        commit1: str = "HEAD",
        commit2: str = "HEAD",
    ) -> DiffResult:
        """Compare the same file path across two different repositories.

        Args:
            repo1: First GitPython Repo instance
            repo2: Second GitPython Repo instance
            file_path: Path to file within repositories
            commit1: Commit hash in first repo (default: HEAD)
            commit2: Commit hash in second repo (default: HEAD)

        Returns:
            DiffResult with unified diff, line-by-line diff, and stats
        """
        try:
            # Get file content from both repositories
            commit1_obj = repo1.commit(commit1)
            commit2_obj = repo2.commit(commit2)

            try:
                content1 = (
                    commit1_obj.tree[file_path].data_stream.read().decode("utf-8")
                )
            except KeyError:
                content1 = ""
                logger.warning(
                    "File %s not found in repo1 at commit %s", file_path, commit1
                )

            try:
                content2 = (
                    commit2_obj.tree[file_path].data_stream.read().decode("utf-8")
                )
            except KeyError:
                content2 = ""
                logger.warning(
                    "File %s not found in repo2 at commit %s", file_path, commit2
                )

            # Generate diff
            lines1 = content1.splitlines(keepends=True)
            lines2 = content2.splitlines(keepends=True)

            diff_lines = self.unified_diff(lines1, lines2)
            line_by_line, stats = self.line_by_line_diff(content1, content2)

            return DiffResult(
                diff_lines=diff_lines, line_by_line=line_by_line, stats=stats
            )

        except Exception as e:
            logger.error("Error comparing files across repos: %s", e)
            raise

    def compare_text_content(self, content1: str, content2: str) -> DiffResult:
        """Compare two text strings directly.

        Args:
            content1: First text content
            content2: Second text content

        Returns:
            DiffResult with unified diff, line-by-line diff, and stats
        """
        lines1 = content1.splitlines(keepends=True)
        lines2 = content2.splitlines(keepends=True)

        diff_lines = self.unified_diff(lines1, lines2)
        line_by_line, stats = self.line_by_line_diff(content1, content2)

        return DiffResult(diff_lines=diff_lines, line_by_line=line_by_line, stats=stats)
