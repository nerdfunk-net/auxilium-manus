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
    commit_result = git_service.commit(
        repository_dict,
        message="Updated configuration",
        files=["config.yaml"],
    )
    git_service.push(repository_dict)
"""

from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from git import Repo
from git.exc import GitCommandError, InvalidGitRepositoryError, NoSuchPathError

from core.safe_urls import validate_git_remote_url
from models.failure import FailureInfo
from services.git.auth import GitAuthenticationService, strip_http_userinfo
from services.git.config import set_git_author
from services.git.env import build_git_env_overrides
from services.git.failure import (
    GitOperationError,
    annotate_failure,
    classify_git_exception,
    classify_git_text,
)
from services.git.paths import repo_path as get_repo_path
from services.git.refs import validate_branch_name
from services.git.repo_lock import ensure_current_lease_held
from services.git.scrub import scrub_url_credentials

logger = logging.getLogger(__name__)


@dataclass
class GitResult:
    """Result of a Git operation."""

    success: bool
    message: str
    details: dict[str, Any] | None = None
    # Why it failed (models.failure); None on success and for failures not classified.
    failure: FailureInfo | None = None

    def error(self) -> GitOperationError:
        """The exception to raise when this failed result must abort a step."""
        return GitOperationError(self.message, failure=self.failure)


@dataclass
class CommitResult(GitResult):
    """Result of a commit operation."""

    commit_sha: str | None = None
    files_changed: int = 0


@dataclass
class PushResult(GitResult):
    """Result of a push operation."""

    pushed: bool = False
    branch: str | None = None


@dataclass
class PullResult(GitResult):
    """Result of a pull operation."""

    commits_pulled: int = 0
    branch: str | None = None


def _scrub_remote_userinfo(repo: Repo) -> None:
    """Remove credentials a working tree created by an older version may hold in ``origin``."""
    try:
        origin = repo.remotes.origin
        current = list(origin.urls)[0]
        clean = strip_http_userinfo(current)
        if clean != current:
            origin.set_url(clean)
            logger.warning(
                "Removed embedded credentials from the origin URL of a legacy working tree; "
                "rotate the token that was stored there"
            )
    except Exception as exc:
        # GitPython's message embeds the set-url command (the URL): log the type only.
        logger.warning("Could not scrub origin URL (%s)", type(exc).__name__)


def _branch_of(repository: dict) -> str:
    """The repository's branch, validated again for rows stored before the allow-list (S4-03)."""
    return validate_branch_name(repository.get("branch", "main"))


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

    def get_repo_path(self, repository: dict) -> Path:
        """Get the filesystem path for a repository.

        Args:
            repository: Repository metadata dict

        Returns:
            Path to the repository directory
        """
        return get_repo_path(repository)

    def open_or_clone(self, repository: dict) -> Repo:
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
            UnsafeURLError: If the repository URL fails the outbound git URL policy
        """
        validate_git_remote_url(
            repository.get("url", ""),
            resolve_dns=True,
            verify_ssl=repository.get("verify_ssl", True),
        )

        repo_dir = self.get_repo_path(repository)
        repo_dir.mkdir(parents=True, exist_ok=True)

        expected_url_norm = (
            self._auth.normalize_url(repository["url"]) if repository.get("url") else None
        )

        try:
            repo = Repo(repo_dir)
        except InvalidGitRepositoryError, NoSuchPathError:
            return self._clone_fresh(repository, repo_dir)  # empty directory or not a repository

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
                shutil.rmtree(repo_dir, ignore_errors=True)  # an intended re-clone
                return self._clone_fresh(repository, repo_dir)
            _scrub_remote_userinfo(repo)
        # C5-01: HEAD is the configured branch. Every other exception propagates (C5-03):
        # a transient error must never delete a tree holding unpushed work.
        self.ensure_branch(repo, _branch_of(repository))
        return repo

    def ensure_branch(self, repo: Repo, branch: str) -> None:
        """HEAD must be *branch* before any pull/commit/push that assumes it (C5-01).

        A clean tree on another branch is switched; a dirty one is refused with a message that
        names the Git Clone step as the reset."""
        if not repo.head.is_valid():
            return  # empty repository
        try:
            current: str | None = repo.active_branch.name
        except TypeError:
            current = None  # detached HEAD
        if current == branch:
            return
        if repo.is_dirty(untracked_files=True):
            raise GitOperationError(
                f"The working tree is on {current or 'a detached HEAD'} with uncommitted "
                f"changes, but {branch!r} is expected. Run the Git Clone step to reset the "
                "working tree.",
                failure=FailureInfo(phase="git", kind="repo_locked", hint="wait_for_other_run"),
            )
        if branch in repo.heads:
            repo.git.checkout(branch)
        else:
            repo.git.checkout("-B", branch, f"origin/{branch}")

    def clone(self, repository: dict, target_path: str | Path | None = None) -> Repo:
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

        # An explicit clone replaces the tree. The old one is set aside first and only deleted
        # once the new clone succeeded; a failed clone restores it (C5R-03).
        aside: Path | None = None
        if path.exists() and any(path.iterdir()):
            aside = path.with_name(
                f"{path.name}.replaced-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
            )
            path.rename(aside)
        try:
            repo = self._clone_fresh(repository, path)
        except Exception:
            if aside is not None:
                shutil.rmtree(path, ignore_errors=True)
                aside.rename(path)
            raise
        if aside is not None:
            shutil.rmtree(aside, ignore_errors=True)
        return repo

    def _clone_fresh(self, repository: dict, target_path: Path) -> Repo:
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
            UnsafeURLError: If the repository URL fails the outbound git URL policy
        """
        validate_git_remote_url(
            repository.get("url", ""),
            resolve_dns=True,
            verify_ssl=repository.get("verify_ssl", True),
        )

        # An unusable tree is moved aside, not deleted: uncommitted artifacts of a crashed
        # writer must not vanish silently (C5-03). An empty directory is simply reused.
        if target_path.exists() and any(target_path.iterdir()):
            aside = target_path.with_name(
                f"{target_path.name}.corrupt-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
            )
            try:
                target_path.rename(aside)
                logger.warning("Moved unusable working tree aside to %s", aside)
            except Exception as e:
                logger.warning("Failed to move aside existing repo dir: %s", e)
                shutil.rmtree(target_path, ignore_errors=True)

        target_path.mkdir(parents=True, exist_ok=True)

        try:
            with self._auth.setup_auth_environment(repository) as (
                clone_url,
                username,
                token,
                ssh_key_path,
            ):
                overrides = build_git_env_overrides(
                    repository, ssh_key_path=ssh_key_path, username=username, token=token
                )
                repo = Repo.clone_from(
                    clone_url,
                    target_path,
                    branch=_branch_of(repository),
                    env=overrides,
                )
                logger.info(
                    "Cloned repository %s from %s",
                    repository.get("name"),
                    repository.get("url"),
                )
                return repo
        except Exception as clone_exc:
            annotate_failure(clone_exc)
            # Cleanup partial clone on failure
            try:
                if target_path.exists():
                    shutil.rmtree(target_path)
            except Exception:
                logger.debug("Could not remove partial clone at %s", target_path, exc_info=True)
            raise

    def pull(self, repository: dict, repo: Repo | None = None) -> PullResult:
        """Pull latest changes from remote repository.

        Args:
            repository: Repository metadata dict
            repo: Optional existing Repo instance (will open if not provided)

        Returns:
            PullResult with operation status
        """
        try:
            validate_git_remote_url(
                repository.get("url", ""),
                resolve_dns=True,
                verify_ssl=repository.get("verify_ssl", True),
            )

            if repo is None:
                repo = self.open_or_clone(repository)

            branch = _branch_of(repository)
            # never merge origin/<branch> into some other branch
            self.ensure_branch(repo, branch)

            with self._auth.setup_auth_environment(repository) as (
                _clean_url,
                username,
                token,
                ssh_key_path,
            ):
                overrides = build_git_env_overrides(
                    repository, ssh_key_path=ssh_key_path, username=username, token=token
                )
                origin = repo.remotes.origin

                # origin.pull() returns one FetchInfo per ref fetched — that count is 1 even
                # when the branch was already up to date, so it is not a commit count.
                # Diff HEAD before/after to count commits actually pulled.
                head_before = repo.head.commit.hexsha if repo.head.is_valid() else None
                with repo.git.custom_environment(**overrides):
                    origin.pull(branch)
                head_after = repo.head.commit.hexsha if repo.head.is_valid() else None

                if head_before and head_after and head_before != head_after:
                    commits_pulled = sum(
                        1 for _ in repo.iter_commits(f"{head_before}..{head_after}")
                    )
                else:
                    commits_pulled = 0

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

        except GitCommandError as e:
            logger.error("Git pull failed: %s", scrub_url_credentials(str(e)))
            return PullResult(
                success=False,
                message=f"Pull failed: {scrub_url_credentials(str(e))}",
                branch=repository.get("branch", "main"),
                failure=classify_git_exception(e),
            )
        except Exception as e:
            logger.error("Unexpected error during pull: %s", scrub_url_credentials(str(e)))
            return PullResult(
                success=False,
                message=f"Unexpected error: {scrub_url_credentials(str(e))}",
                branch=repository.get("branch", "main"),
                failure=classify_git_exception(e),
            )

    def checkout_new_branch(self, repo: Repo, name: str, base_ref: str) -> None:
        """Create (or reset) a local branch ``name`` starting from ``base_ref``
        and check it out. ``git checkout -B`` is used so a retry of a failed
        stage run is idempotent. Raises on any git error — callers convert to a
        ``RuntimeError``.
        """
        try:
            repo.git.checkout("-B", name, base_ref)
            logger.info("Checked out branch %s from %s", name, base_ref)
        except GitCommandError as e:
            logger.error("checkout -B %s from %s failed: %s", name, base_ref, e)
            raise

    def diff_refs(self, repo: Repo, ref_a: str, ref_b: str) -> str:
        """Unified whole-tree diff of what ``ref_b`` adds on top of ``ref_a``
        (two-dot ``ref_a..ref_b``). Returns the raw ``git diff`` text.
        """
        return repo.git.diff(f"{ref_a}..{ref_b}")

    def push(
        self,
        repository: dict,
        repo: Repo | None = None,
        branch: str | None = None,
        *,
        force: bool = False,
    ) -> PushResult:
        """Push local commits to remote repository.

        Supports both SSH key and token authentication. For token auth,
        temporarily updates the remote URL with credentials.

        Args:
            repository: Repository metadata dict
            repo: Optional existing Repo instance (will open if not provided)
            branch: Optional branch name (uses repository config if not provided)
            force: If True, force-push (``+ref:ref``). Used for per-change
                branches whose local ref may have been reset by ``checkout -B``.

        Returns:
            PushResult with operation status
        """
        ensure_current_lease_held()
        try:
            validate_git_remote_url(
                repository.get("url", ""),
                resolve_dns=True,
                verify_ssl=repository.get("verify_ssl", True),
            )

            if repo is None:
                repo = self.open_or_clone(repository)

            push_branch = validate_branch_name(branch or repository.get("branch", "main"))

            with self._auth.setup_auth_environment(repository) as (
                _clean_url,
                username,
                token,
                ssh_key_path,
            ):
                overrides = build_git_env_overrides(
                    repository, ssh_key_path=ssh_key_path, username=username, token=token
                )
                origin = repo.remotes.origin

                refspec = f"{'+' if force else ''}{push_branch}:{push_branch}"
                with repo.git.custom_environment(**overrides):
                    push_info = origin.push(refspec=refspec)

                # Check push result
                if push_info:
                    for info in push_info:
                        if info.flags & info.ERROR:
                            return PushResult(
                                success=False,
                                message=f"Push failed: {info.summary}",
                                pushed=False,
                                branch=push_branch,
                                failure=classify_git_text(info.summary or ""),
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

        except GitCommandError as e:
            err_str = scrub_url_credentials(str(e))
            logger.error("Git push failed: %s", err_str)

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
                failure=classify_git_exception(e),
            )
        except Exception as e:
            logger.error("Unexpected error during push: %s", scrub_url_credentials(str(e)))
            return PushResult(
                success=False,
                message=f"Unexpected error: {scrub_url_credentials(str(e))}",
                pushed=False,
                branch=branch or repository.get("branch", "main"),
                failure=classify_git_exception(e),
            )

    def commit(
        self,
        repository: dict,
        message: str,
        files: list[str] | None = None,
        repo: Repo | None = None,
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
        ensure_current_lease_held()
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

            logger.info("Created commit %s with %s files", commit.hexsha[:8], len(changed_files))

            return CommitResult(
                success=True,
                message=f"Committed {len(changed_files)} files",
                commit_sha=commit.hexsha,
                files_changed=len(changed_files),
            )

        except GitCommandError as e:
            logger.error("Git commit failed: %s", scrub_url_credentials(str(e)))
            return CommitResult(
                success=False,
                message=f"Commit failed: {scrub_url_credentials(str(e))}",
                failure=classify_git_exception(e),
            )
        except Exception as e:
            logger.error("Unexpected error during commit: %s", scrub_url_credentials(str(e)))
            return CommitResult(
                success=False,
                message=f"Unexpected error: {scrub_url_credentials(str(e))}",
                failure=classify_git_exception(e),
            )

    def fetch(self, repository: dict, repo: Repo | None = None) -> GitResult:
        """Fetch updates from remote without merging.

        Args:
            repository: Repository metadata dict
            repo: Optional existing Repo instance (will open if not provided)

        Returns:
            GitResult with operation status
        """
        try:
            validate_git_remote_url(
                repository.get("url", ""),
                resolve_dns=True,
                verify_ssl=repository.get("verify_ssl", True),
            )

            if repo is None:
                repo = self.open_or_clone(repository)

            with self._auth.setup_auth_environment(repository) as (
                _clean_url,
                username,
                token,
                ssh_key_path,
            ):
                overrides = build_git_env_overrides(
                    repository, ssh_key_path=ssh_key_path, username=username, token=token
                )
                origin = repo.remotes.origin

                with repo.git.custom_environment(**overrides):
                    origin.fetch()

                logger.info("Fetched updates from %s", repository.get("name"))
                return GitResult(
                    success=True,
                    message="Successfully fetched updates",
                )

        except Exception as e:
            logger.error("Fetch failed: %s", scrub_url_credentials(str(e)))
            return GitResult(
                success=False,
                message=f"Fetch failed: {scrub_url_credentials(str(e))}",
                failure=classify_git_exception(e),
            )
