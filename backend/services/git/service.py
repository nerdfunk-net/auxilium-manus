"""
Central Git Service.

This module provides a unified, high-level interface for all Git operations
across the application. It consolidates functionality from various git-related
services and ensures consistent authentication (SSH key and token) support
for all operations.

Key Features:
- Unified clone, pull, push, commit operations
- Consistent SSH key and token authentication
- SSL/TLS configuration handling
- Git author configuration for commits
- Proper error handling and logging

Usage:
    import service_factory
    git_service = service_factory.build_git_service()

    # Clone or open a repository
    repo = git_service.open_or_clone(repository_dict)

    # Commit and push changes
    result = git_service.commit_and_push(
        repository_dict,
        message="Updated configuration",
        files=["config.yaml"]
    )
"""

from __future__ import annotations

import logging
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError

from services.git.auth import GitAuthenticationService
from services.git.config import set_git_author
from services.git.env import set_ssl_env
from services.git.paths import repo_path as get_repo_path

logger = logging.getLogger(__name__)


@dataclass
class GitResult:
    """Result of a Git operation."""

    success: bool
    message: str
    details: Optional[Dict[str, Any]] = None


@dataclass
class CommitResult(GitResult):
    """Result of a commit operation."""

    commit_sha: Optional[str] = None
    files_changed: int = 0


@dataclass
class PushResult(GitResult):
    """Result of a push operation."""

    pushed: bool = False
    branch: Optional[str] = None


@dataclass
class PullResult(GitResult):
    """Result of a pull operation."""

    commits_pulled: int = 0
    branch: Optional[str] = None


@dataclass
class CommitAndPushResult(GitResult):
    """Result of a combined commit and push operation."""

    commit_sha: Optional[str] = None
    files_changed: int = 0
    pushed: bool = False
    branch: Optional[str] = None


class GitService:
    """Central service for all Git repository operations.

    This service provides a unified interface for Git operations with
    consistent authentication support (SSH key and token) across all methods.

    All methods that interact with remote repositories properly handle:
    - SSH key authentication via GIT_SSH_COMMAND
    - Token/password authentication via URL injection
    - SSL/TLS certificate verification settings
    - Git author configuration for commits

    Example:
        >>> import service_factory; git_service = service_factory.build_git_service()
        >>>
        >>> # Repository configuration
        >>> repo_config = {
        ...     "name": "my-configs",
        ...     "url": "git@gitlab.example.com:team/configs.git",
        ...     "branch": "main",
        ...     "auth_type": "ssh_key",
        ...     "credential_name": "gitlab-ssh-key",
        ...     "git_author_name": "Cockpit-NG",
        ...     "git_author_email": "automation@example.com"
        ... }
        >>>
        >>> # Open or clone repository
        >>> repo = git_service.open_or_clone(repo_config)
        >>>
        >>> # Make changes and commit/push
        >>> result = git_service.commit_and_push(
        ...     repo_config,
        ...     message="Backup config 2024-01-15",
        ...     files=["router1.cfg", "router2.cfg"]
        ... )
    """

    def __init__(self):
        self._auth = GitAuthenticationService()

    def get_repo_path(self, repository: Dict) -> Path:
        """Get the filesystem path for a repository.

        Args:
            repository: Repository metadata dict

        Returns:
            Path to the repository directory
        """
        return get_repo_path(repository)

    def open_or_clone(self, repository: Dict) -> Repo:
        """Open an existing repository or clone it if it doesn't exist.

        This method handles:
        - Opening existing valid repositories
        - Re-cloning if URL mismatch detected
        - Initial cloning with proper authentication

        Args:
            repository: Repository metadata dict with url, branch, auth info

        Returns:
            GitPython Repo instance

        Raises:
            GitCommandError: If clone operation fails
            InvalidGitRepositoryError: If repository is invalid and re-clone fails
        """
        repo_dir = self.get_repo_path(repository)
        repo_dir.mkdir(parents=True, exist_ok=True)

        expected_url_norm = (
            self._auth.normalize_url(repository["url"])
            if repository.get("url")
            else None
        )

        try:
            repo = Repo(repo_dir)
            # Validate remote URL if present
            try:
                current_remote = repo.remotes.origin.url if repo.remotes else None
            except Exception:
                current_remote = None

            if expected_url_norm and current_remote:
                current_url_norm = self._auth.normalize_url(current_remote)
                if current_url_norm != expected_url_norm:
                    logger.warning(
                        "Repository URL mismatch. Expected: %s, Found: %s; re-cloning",
                        expected_url_norm,
                        current_url_norm,
                    )
                    raise InvalidGitRepositoryError("URL mismatch, need to re-clone")

            return repo
        except Exception:
            return self._clone_fresh(repository, repo_dir)

    def clone(
        self, repository: Dict, target_path: Optional[Union[str, Path]] = None
    ) -> Repo:
        """Clone a repository to a specific path.

        Args:
            repository: Repository metadata dict with url, branch, auth info
            target_path: Optional target path (uses default if not provided)

        Returns:
            GitPython Repo instance

        Raises:
            GitCommandError: If clone operation fails
        """
        if target_path:
            path = Path(target_path)
        else:
            path = self.get_repo_path(repository)

        return self._clone_fresh(repository, path)

    def _clone_fresh(self, repository: Dict, target_path: Path) -> Repo:
        """Clone a repository fresh to the target path.

        Internal method that handles the actual clone operation with
        proper cleanup on failure.

        Args:
            repository: Repository metadata dict
            target_path: Path where repository should be cloned

        Returns:
            GitPython Repo instance

        Raises:
            GitCommandError: If clone operation fails
        """
        # Clean up existing directory if present
        if target_path.exists():
            try:
                shutil.rmtree(target_path)
            except Exception as e:
                logger.warning("Failed to remove existing repo dir: %s", e)

        target_path.mkdir(parents=True, exist_ok=True)

        try:
            with set_ssl_env(repository):
                with self._auth.setup_auth_environment(repository) as (
                    clone_url,
                    username,
                    token,
                    ssh_key_path,
                ):
                    repo = Repo.clone_from(
                        clone_url,
                        target_path,
                        branch=repository.get("branch", "main"),
                    )
                    logger.info(
                        "Cloned repository %s from %s",
                        repository.get("name"),
                        repository.get("url"),
                    )
                    return repo
        except Exception:
            # Cleanup partial clone on failure
            try:
                if target_path.exists():
                    shutil.rmtree(target_path)
            except Exception:
                pass
            raise

    def pull(self, repository: Dict, repo: Optional[Repo] = None) -> PullResult:
        """Pull latest changes from remote repository.

        Args:
            repository: Repository metadata dict
            repo: Optional existing Repo instance (will open if not provided)

        Returns:
            PullResult with operation status
        """
        try:
            if repo is None:
                repo = self.open_or_clone(repository)

            branch = repository.get("branch", "main")

            with set_ssl_env(repository):
                with self._auth.setup_auth_environment(repository) as (
                    auth_url,
                    username,
                    token,
                    ssh_key_path,
                ):
                    origin = repo.remotes.origin
                    original_url = None

                    try:
                        # For token auth, temporarily update remote URL
                        if token and not ssh_key_path:
                            original_url = list(origin.urls)[0]
                            origin.set_url(auth_url)

                        # Perform pull
                        pull_info = origin.pull(branch)
                        commits_pulled = len(pull_info) if pull_info else 0

                        logger.info(
                            "Pulled %s commits from %s",
                            commits_pulled,
                            repository.get("name"),
                        )

                        return PullResult(
                            success=True,
                            message=f"Successfully pulled {commits_pulled} commits",
                            commits_pulled=commits_pulled,
                            branch=branch,
                        )
                    finally:
                        # Restore original URL for token auth
                        if original_url:
                            try:
                                origin.set_url(original_url)
                            except Exception:
                                pass

        except GitCommandError as e:
            logger.error("Git pull failed: %s", e)
            return PullResult(
                success=False,
                message=f"Pull failed: {str(e)}",
                branch=repository.get("branch", "main"),
            )
        except Exception as e:
            logger.error("Unexpected error during pull: %s", e)
            return PullResult(
                success=False,
                message=f"Unexpected error: {str(e)}",
                branch=repository.get("branch", "main"),
            )

    def push(
        self,
        repository: Dict,
        repo: Optional[Repo] = None,
        branch: Optional[str] = None,
    ) -> PushResult:
        """Push local commits to remote repository.

        Supports both SSH key and token authentication. For token auth,
        temporarily updates the remote URL with credentials.

        Args:
            repository: Repository metadata dict
            repo: Optional existing Repo instance (will open if not provided)
            branch: Optional branch name (uses repository config if not provided)

        Returns:
            PushResult with operation status
        """
        try:
            if repo is None:
                repo = self.open_or_clone(repository)

            push_branch = branch or repository.get("branch", "main")

            with set_ssl_env(repository):
                with self._auth.setup_auth_environment(repository) as (
                    auth_url,
                    username,
                    token,
                    ssh_key_path,
                ):
                    origin = repo.remotes.origin
                    original_url = None

                    try:
                        # For token auth, temporarily update remote URL
                        if token and not ssh_key_path:
                            original_url = list(origin.urls)[0]
                            origin.set_url(auth_url)

                        # Perform push
                        push_info = origin.push(refspec=f"{push_branch}:{push_branch}")

                        # Check push result
                        if push_info:
                            for info in push_info:
                                if info.flags & info.ERROR:
                                    return PushResult(
                                        success=False,
                                        message=f"Push failed: {info.summary}",
                                        pushed=False,
                                        branch=push_branch,
                                    )

                        logger.info(
                            "Successfully pushed to %s branch %s",
                            repository.get("name"),
                            push_branch,
                        )

                        return PushResult(
                            success=True,
                            message=f"Successfully pushed to {push_branch}",
                            pushed=True,
                            branch=push_branch,
                        )
                    finally:
                        # Restore original URL for token auth
                        if original_url:
                            try:
                                origin.set_url(original_url)
                            except Exception:
                                pass

        except GitCommandError as e:
            err_str = str(e)
            logger.error("Git push failed: %s", e)

            if "authentication" in err_str.lower():
                message = "Authentication failed. Please check your Git credentials."
            elif "rejected" in err_str.lower():
                message = "Push rejected. Try pulling first to merge remote changes."
            else:
                message = f"Push failed: {err_str}"

            return PushResult(
                success=False,
                message=message,
                pushed=False,
                branch=branch or repository.get("branch", "main"),
            )
        except Exception as e:
            logger.error("Unexpected error during push: %s", e)
            return PushResult(
                success=False,
                message=f"Unexpected error: {str(e)}",
                pushed=False,
                branch=branch or repository.get("branch", "main"),
            )

    def commit(
        self,
        repository: Dict,
        message: str,
        files: Optional[List[str]] = None,
        repo: Optional[Repo] = None,
        add_all: bool = False,
    ) -> CommitResult:
        """Commit changes to the local repository.

        Args:
            repository: Repository metadata dict (for git author config)
            message: Commit message
            files: Optional list of files to stage (relative paths)
            repo: Optional existing Repo instance (will open if not provided)
            add_all: If True, stage all changes (git add .)

        Returns:
            CommitResult with operation status
        """
        try:
            if repo is None:
                repo = self.open_or_clone(repository)

            # Stage files
            if add_all:
                repo.git.add(".")
            elif files:
                for file_path in files:
                    repo.index.add([file_path])

            # Check if there are changes to commit
            changed_files = repo.git.diff("--cached", "--name-only").split("\n")
            changed_files = [f for f in changed_files if f.strip()]

            if not changed_files:
                return CommitResult(
                    success=True,
                    message="No changes to commit",
                    files_changed=0,
                )

            # Commit with git author configuration
            with set_git_author(repository, repo):
                commit = repo.index.commit(message)

            logger.info(
                "Created commit %s with %s files", commit.hexsha[:8], len(changed_files)
            )

            return CommitResult(
                success=True,
                message=f"Committed {len(changed_files)} files",
                commit_sha=commit.hexsha,
                files_changed=len(changed_files),
            )

        except GitCommandError as e:
            logger.error("Git commit failed: %s", e)
            return CommitResult(
                success=False,
                message=f"Commit failed: {str(e)}",
            )
        except Exception as e:
            logger.error("Unexpected error during commit: %s", e)
            return CommitResult(
                success=False,
                message=f"Unexpected error: {str(e)}",
            )

    def commit_and_push(
        self,
        repository: Dict,
        message: str,
        files: Optional[List[str]] = None,
        repo: Optional[Repo] = None,
        add_all: bool = False,
        branch: Optional[str] = None,
    ) -> CommitAndPushResult:
        """Commit changes and push to remote in one operation.

        This is the most common workflow for automated changes. It:
        1. Stages specified files (or all changes)
        2. Creates a commit with the specified message
        3. Pushes to the remote repository

        Args:
            repository: Repository metadata dict
            message: Commit message
            files: Optional list of files to stage (relative paths)
            repo: Optional existing Repo instance (will open if not provided)
            add_all: If True, stage all changes (git add .)
            branch: Optional branch name for push (uses repository config if not provided)

        Returns:
            CommitAndPushResult with operation status
        """
        try:
            if repo is None:
                repo = self.open_or_clone(repository)

            # Step 1: Commit
            commit_result = self.commit(
                repository=repository,
                message=message,
                files=files,
                repo=repo,
                add_all=add_all,
            )

            if not commit_result.success:
                return CommitAndPushResult(
                    success=False,
                    message=commit_result.message,
                    commit_sha=None,
                    files_changed=0,
                    pushed=False,
                    branch=branch or repository.get("branch", "main"),
                )

            # If no changes were committed, skip push
            if commit_result.files_changed == 0:
                return CommitAndPushResult(
                    success=True,
                    message="No changes to commit or push",
                    commit_sha=None,
                    files_changed=0,
                    pushed=False,
                    branch=branch or repository.get("branch", "main"),
                )

            # Step 2: Push
            push_result = self.push(
                repository=repository,
                repo=repo,
                branch=branch,
            )

            if not push_result.success:
                return CommitAndPushResult(
                    success=False,
                    message=f"Commit succeeded but push failed: {push_result.message}",
                    commit_sha=commit_result.commit_sha,
                    files_changed=commit_result.files_changed,
                    pushed=False,
                    branch=push_result.branch,
                )

            return CommitAndPushResult(
                success=True,
                message=f"Successfully committed and pushed {commit_result.files_changed} files",
                commit_sha=commit_result.commit_sha,
                files_changed=commit_result.files_changed,
                pushed=True,
                branch=push_result.branch,
            )

        except Exception as e:
            logger.error("Unexpected error in commit_and_push: %s", e)
            return CommitAndPushResult(
                success=False,
                message=f"Unexpected error: {str(e)}",
                pushed=False,
                branch=branch or repository.get("branch", "main"),
            )

    def fetch(self, repository: Dict, repo: Optional[Repo] = None) -> GitResult:
        """Fetch updates from remote without merging.

        Args:
            repository: Repository metadata dict
            repo: Optional existing Repo instance (will open if not provided)

        Returns:
            GitResult with operation status
        """
        try:
            if repo is None:
                repo = self.open_or_clone(repository)

            with set_ssl_env(repository):
                with self._auth.setup_auth_environment(repository) as (
                    auth_url,
                    username,
                    token,
                    ssh_key_path,
                ):
                    origin = repo.remotes.origin
                    original_url = None

                    try:
                        if token and not ssh_key_path:
                            original_url = list(origin.urls)[0]
                            origin.set_url(auth_url)

                        origin.fetch()

                        logger.info("Fetched updates from %s", repository.get("name"))
                        return GitResult(
                            success=True,
                            message="Successfully fetched updates",
                        )
                    finally:
                        if original_url:
                            try:
                                origin.set_url(original_url)
                            except Exception:
                                pass

        except Exception as e:
            logger.error("Fetch failed: %s", e)
            return GitResult(
                success=False,
                message=f"Fetch failed: {str(e)}",
            )

    def get_status(
        self, repository: Dict, repo: Optional[Repo] = None
    ) -> Dict[str, Any]:
        """Get comprehensive repository status.

        Args:
            repository: Repository metadata dict
            repo: Optional existing Repo instance

        Returns:
            Dictionary with status information
        """
        repo_path = self.get_repo_path(repository)

        status = {
            "exists": repo_path.exists(),
            "is_git_repo": False,
            "current_branch": None,
            "current_commit": None,
            "is_dirty": False,
            "untracked_files": [],
            "modified_files": [],
            "staged_files": [],
        }

        if not status["exists"]:
            return status

        try:
            if repo is None:
                repo = Repo(repo_path)

            status["is_git_repo"] = True

            try:
                status["current_branch"] = repo.active_branch.name
            except Exception:
                status["current_branch"] = "HEAD"

            try:
                if repo.head.is_valid():
                    commit = repo.head.commit
                    status["current_commit"] = {
                        "sha": commit.hexsha[:8],
                        "message": commit.message.strip(),
                        "author": commit.author.name,
                        "date": commit.committed_datetime.isoformat(),
                    }
            except Exception:
                pass

            status["is_dirty"] = repo.is_dirty()
            status["untracked_files"] = repo.untracked_files
            status["modified_files"] = [item.a_path for item in repo.index.diff(None)]
            status["staged_files"] = (
                [item.a_path for item in repo.index.diff("HEAD")]
                if repo.head.is_valid()
                else []
            )

        except InvalidGitRepositoryError:
            status["is_git_repo"] = False
        except Exception as e:
            logger.warning("Error getting repository status: %s", e)
            status["error"] = str(e)

        return status

    @contextmanager
    def with_auth_environment(self, repository: Dict):
        """Context manager to set up authentication environment for Git operations.

        Use this when you need to perform custom Git operations with proper
        authentication configured.

        Args:
            repository: Repository metadata dict

        Yields:
            Tuple of (auth_url, username, token, ssh_key_path)

        Example:
            >>> with git_service.with_auth_environment(repo_config) as (url, user, token, ssh_key):
            ...     # Custom git operations with auth configured
            ...     pass
        """
        with set_ssl_env(repository):
            with self._auth.setup_auth_environment(repository) as auth_info:
                yield auth_info
