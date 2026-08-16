"""
Git Diff Service - Centralized diff operations.

This service consolidates all diff calculation logic that was previously
duplicated across git_version_control.py and git_compare.py.
"""

from __future__ import annotations

import difflib
import logging

from models.git import DiffLine, DiffResult, DiffStats

logger = logging.getLogger(__name__)


class GitDiffService:
    """Service for performing git diff operations."""

    def unified_diff(self, lines1: list[str], lines2: list[str], n: int = 3) -> list[str]:
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

    def calculate_diff_stats(self, diff_lines: list[str]) -> DiffStats:
        """Calculate statistics from unified diff lines.

        Args:
            diff_lines: List of unified diff lines

        Returns:
            DiffStats with additions and deletions count
        """
        additions = sum(
            1 for line in diff_lines if line.startswith("+") and not line.startswith("+++")
        )
        deletions = sum(
            1 for line in diff_lines if line.startswith("-") and not line.startswith("---")
        )

        return DiffStats(additions=additions, deletions=deletions)

    def line_by_line_diff(self, content1: str, content2: str) -> tuple[list[DiffLine], DiffStats]:
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
        parsed_lines: list[DiffLine] = []
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
                parsed_lines.append(DiffLine(line_number=line_number, type="add", content=line[1:]))
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
