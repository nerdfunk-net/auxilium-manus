"""
Git operations models - Consistent data structures for commits, diffs, and operations.

This module provides standardized Pydantic models for all git operations to ensure
consistent data structures across all endpoints and eliminate inconsistencies where
commit author is sometimes a string and sometimes a dict.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from services.git.paths import validate_relative_glob
from services.git.refs import validate_branch_name


class CompareCommitsRequest(BaseModel):
    """Body of ``POST /git/{repo_id}/diff``."""

    model_config = ConfigDict(extra="forbid")

    commit1: str = Field(min_length=1, max_length=255)
    commit2: str = Field(min_length=1, max_length=255)
    file_path: str = Field(min_length=1, max_length=1024)

    @field_validator("commit1", "commit2")
    @classmethod
    def _revision(cls, value: str) -> str:
        # Allow-list (sha, branch or tag spelling, never a leading '-'): a revision must not be
        # parsed as a git option.
        return validate_branch_name(value)

    @field_validator("file_path")
    @classmethod
    def _path(cls, value: str) -> str:
        return validate_relative_glob(value, field="file_path")


# ============================================================================
# Commit Models
# ============================================================================


class GitAuthor(BaseModel):
    """Git commit author information."""

    name: str = Field(..., description="Author name")
    email: str = Field(..., description="Author email address")


class GitCommit(BaseModel):
    """Standard git commit representation used across all endpoints."""

    hash: str = Field(..., description="Full commit SHA hash")
    short_hash: str = Field(..., description="Short commit SHA (8 chars)")
    message: str = Field(..., description="Commit message")
    author: GitAuthor = Field(..., description="Commit author information")
    date: str = Field(..., description="Commit date in ISO format")
    files_changed: int = Field(default=0, description="Number of files changed in commit")


class CommitStats(BaseModel):
    """Statistics for a commit."""

    additions: int = Field(default=0, description="Lines added")
    deletions: int = Field(default=0, description="Lines deleted")
    changes: int = Field(default=0, description="Total changes (additions + deletions)")
    total_lines: int = Field(default=0, description="Total lines in changed files after commit")


# ============================================================================
# Diff Models
# ============================================================================


class DiffStats(BaseModel):
    """Statistics for a diff operation."""

    additions: int = Field(default=0, description="Lines added")
    deletions: int = Field(default=0, description="Lines deleted")


class DiffLine(BaseModel):
    """Single line in a diff with metadata."""

    line_number: int = Field(..., description="Line number in the file")
    type: Literal["add", "remove", "context"] = Field(..., description="Type of diff line")
    content: str = Field(..., description="Line content")


class DiffResult(BaseModel):
    """Result of a diff operation between two versions."""

    diff_lines: list[str] = Field(default_factory=list, description="Unified diff format lines")
    line_by_line: list[DiffLine] = Field(
        default_factory=list, description="Parsed diff lines with metadata"
    )
    stats: DiffStats = Field(..., description="Diff statistics")


# ============================================================================
# Operation Result Models
# ============================================================================


class SyncResult(BaseModel):
    """Result of a repository sync operation."""

    success: bool = Field(..., description="Whether sync was successful")
    message: str = Field(..., description="Human-readable result message")
    commits_behind: int = Field(
        default=0, description="Number of commits behind remote before sync"
    )
    commits_ahead: int = Field(
        default=0, description="Number of commits ahead of remote after sync"
    )
    repository_path: str | None = Field(None, description="Local path to repository")


# ============================================================================
# File History Models
# ============================================================================


class FileHistoryCommit(GitCommit):
    """Commit in file history with change type information."""

    change_type: Literal["added", "modified", "deleted", "renamed"] = Field(
        ..., description="Type of change made to file in this commit"
    )
    old_path: str | None = Field(None, description="Previous file path if renamed")


# ============================================================================
# Branch Models
# ============================================================================


# ============================================================================
# Comparison Models
# ============================================================================


# ============================================================================
# Request Models (for backwards compatibility with existing endpoints)
# ============================================================================


class GitCommitRequest(BaseModel):
    """Git commit request model."""

    message: str
    files: list[str] | None = None  # If None, commit all changes


class GitBranchRequest(BaseModel):
    """Git branch management request model."""

    branch_name: str
    create: bool = False


# ============================================================================
# Helper Functions
# ============================================================================


def commit_to_dict(commit) -> dict:
    """Convert a GitPython commit object to a dictionary matching GitCommit model.

    Args:
        commit: GitPython Commit object

    Returns:
        Dictionary with standardized commit fields
    """
    return {
        "hash": commit.hexsha,
        "short_hash": commit.hexsha[:8],
        "message": commit.message.strip(),
        "author": {
            "name": commit.author.name,
            "email": commit.author.email,
        },
        "date": commit.committed_datetime.isoformat(),
        "files_changed": len(commit.stats.files) if hasattr(commit, "stats") else 0,
    }
