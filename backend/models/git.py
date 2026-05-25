"""
Git operations models - Consistent data structures for commits, diffs, and operations.

This module provides standardized Pydantic models for all git operations to ensure
consistent data structures across all endpoints and eliminate inconsistencies where
commit author is sometimes a string and sometimes a dict.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

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
    files_changed: int = Field(
        default=0, description="Number of files changed in commit"
    )


class GitCommitDetails(GitCommit):
    """Detailed commit information with stats and optional diff."""

    stats: CommitStats = Field(..., description="Commit statistics")
    diff: Optional[str] = Field(None, description="Full diff content if requested")


class CommitStats(BaseModel):
    """Statistics for a commit."""

    additions: int = Field(default=0, description="Lines added")
    deletions: int = Field(default=0, description="Lines deleted")
    changes: int = Field(default=0, description="Total changes (additions + deletions)")
    total_lines: int = Field(
        default=0, description="Total lines in changed files after commit"
    )


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
    type: Literal["add", "remove", "context"] = Field(
        ..., description="Type of diff line"
    )
    content: str = Field(..., description="Line content")


class DiffResult(BaseModel):
    """Result of a diff operation between two versions."""

    diff_lines: List[str] = Field(
        default_factory=list, description="Unified diff format lines"
    )
    line_by_line: List[DiffLine] = Field(
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
    repository_path: Optional[str] = Field(None, description="Local path to repository")


class CloneResult(BaseModel):
    """Result of a repository clone operation."""

    success: bool = Field(..., description="Whether clone was successful")
    message: str = Field(..., description="Human-readable result message")
    repo_path: str = Field(..., description="Local path to cloned repository")


class StatusInfo(BaseModel):
    """Git repository status information."""

    current_branch: str = Field(..., description="Currently active branch name")
    branches: List[str] = Field(
        default_factory=list, description="List of all branches"
    )
    is_dirty: bool = Field(
        default=False, description="Whether repository has uncommitted changes"
    )
    untracked_files: List[str] = Field(
        default_factory=list, description="List of untracked files"
    )
    modified_files: List[str] = Field(
        default_factory=list, description="List of modified files"
    )
    last_commit: Optional[GitCommit] = Field(
        None, description="Most recent commit information"
    )
    commits_behind: int = Field(
        default=0, description="Number of commits behind remote"
    )
    commits_ahead: int = Field(
        default=0, description="Number of commits ahead of remote"
    )


# ============================================================================
# File History Models
# ============================================================================


class FileHistoryCommit(GitCommit):
    """Commit in file history with change type information."""

    change_type: Literal["added", "modified", "deleted", "renamed"] = Field(
        ..., description="Type of change made to file in this commit"
    )
    old_path: Optional[str] = Field(None, description="Previous file path if renamed")


class FileHistory(BaseModel):
    """Complete history of a file across commits."""

    file_path: str = Field(..., description="Path to the file")
    commits: List[FileHistoryCommit] = Field(
        default_factory=list, description="Commits affecting this file"
    )
    total_commits: int = Field(default=0, description="Total number of commits")


# ============================================================================
# Branch Models
# ============================================================================


class GitBranch(BaseModel):
    """Git branch information."""

    name: str = Field(..., description="Branch name")
    is_current: bool = Field(
        default=False, description="Whether this is the currently active branch"
    )
    last_commit: Optional[GitCommit] = Field(
        None, description="Most recent commit on this branch"
    )
    commit_count: int = Field(
        default=0, description="Total number of commits on this branch"
    )


# ============================================================================
# Comparison Models
# ============================================================================


class CommitComparison(BaseModel):
    """Comparison between two commits."""

    commit1: str = Field(..., description="First commit hash")
    commit2: str = Field(..., description="Second commit hash")
    files_changed: List[str] = Field(
        default_factory=list, description="List of files changed between commits"
    )
    diff: DiffResult = Field(..., description="Diff between commits")


class CrossRepoComparison(BaseModel):
    """Comparison of same file across different repositories."""

    repo1_id: int = Field(..., description="First repository ID")
    repo2_id: int = Field(..., description="Second repository ID")
    file_path: str = Field(..., description="Path to file being compared")
    commit1: Optional[str] = Field(None, description="Commit hash in first repo")
    commit2: Optional[str] = Field(None, description="Commit hash in second repo")
    diff: DiffResult = Field(..., description="Diff between files")


# ============================================================================
# Request Models (for backwards compatibility with existing endpoints)
# ============================================================================


class GitCommitRequest(BaseModel):
    """Git commit request model."""

    message: str
    files: Optional[List[str]] = None  # If None, commit all changes


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


def create_git_commit(commit) -> GitCommit:
    """Create a GitCommit model from a GitPython commit object.

    Args:
        commit: GitPython Commit object

    Returns:
        GitCommit instance with standardized fields
    """
    return GitCommit(**commit_to_dict(commit))
