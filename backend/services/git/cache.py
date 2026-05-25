"""
Git Cache Service - Centralized caching for git operations.

This service consolidates all git caching logic that was previously
scattered across git_operations.py, git_version_control.py, and git_files.py.

Provides consistent cache key generation, TTL management, and cache invalidation
for commits, file history, and other git data.
"""

from __future__ import annotations

import logging
import subprocess
from typing import Any, Dict, List, Optional

from git import Repo

from models.git import GitCommit, commit_to_dict

logger = logging.getLogger(__name__)

_CACHE_DEFAULTS = {"enabled": True, "ttl_seconds": 600, "max_commits": 500}


class GitCacheService:
    """Service for caching git operations data."""

    def __init__(self, cache_service):
        """Initialize the git cache service."""
        self._cache = cache_service
        self._cache_enabled = True
        self._max_commits = 500
        self._ttl_seconds = 600

    def _get_cache_config(self) -> Dict[str, Any]:
        """Get cache configuration."""
        return _CACHE_DEFAULTS

    def _build_cache_key(self, repo_id: int, *parts: str) -> str:
        """Build consistent cache key for git operations.

        Args:
            repo_id: Repository ID
            *parts: Additional key components

        Returns:
            Cache key string in format "repo:{id}:part1:part2:..."
        """
        repo_scope = f"repo:{repo_id}"
        if parts:
            return f"{repo_scope}:{':'.join(parts)}"
        return repo_scope

    def get_commits(
        self,
        repo_id: int,
        repo_path: str,
        branch_name: str,
        limit: int = 50,
        use_models: bool = False,
    ) -> List[Dict[str, Any]] | List[GitCommit]:
        """Get commits for a repository with caching.

        Args:
            repo_id: Repository ID
            repo_path: Path to repository on disk
            branch_name: Branch name to get commits from
            limit: Maximum number of commits to return (default: 50)
            use_models: If True, return GitCommit models; if False, return dicts (default: False)

        Returns:
            List of commit dictionaries or GitCommit models
        """
        cache_cfg = self._get_cache_config()
        cache_key = self._build_cache_key(repo_id, "commits", branch_name)

        # Try cache first if enabled
        if cache_cfg.get("enabled", True):
            cached_commits = self._cache.get(cache_key)
            if cached_commits is not None:
                logger.debug(
                    "Cache hit for commits: repo %s, branch %s", repo_id, branch_name
                )
                limited_commits = cached_commits[:limit]
                if use_models:
                    return [GitCommit(**c) for c in limited_commits]
                return limited_commits

        # Cache miss - fetch from repository
        logger.debug("Cache miss for commits: repo %s, branch %s", repo_id, branch_name)
        commits = self._fetch_commits_from_repo(
            repo_id, repo_path, branch_name, limit, cache_cfg
        )

        if use_models:
            return [GitCommit(**c) for c in commits]
        return commits

    def _fetch_commits_from_repo(
        self,
        repo_id: int,
        repo_path: str,
        branch_name: str,
        limit: int,
        cache_cfg: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Fetch commits from repository using GitPython with subprocess fallback."""
        try:
            repo = Repo(repo_path)
            commits = []

            for commit in repo.iter_commits(branch_name, max_count=limit):
                commits.append(commit_to_dict(commit))

            if cache_cfg.get("enabled", True):
                max_commits = int(cache_cfg.get("max_commits", 500))
                if len(commits) < max_commits:
                    full_commits = []
                    for commit in repo.iter_commits(branch_name, max_count=max_commits):
                        full_commits.append(commit_to_dict(commit))

                    ttl = int(cache_cfg.get("ttl_seconds", 600))
                    cache_key = self._build_cache_key(repo_id, "commits", branch_name)
                    self._cache.set(cache_key, full_commits, ttl)
                    logger.debug(
                        "Cached %s commits for repo %s, branch %s",
                        len(full_commits),
                        repo_id,
                        branch_name,
                    )

            return commits

        except Exception as git_error:
            logger.warning(
                "GitPython failed for repo %s, falling back to subprocess: %s",
                repo_id,
                git_error,
            )
            return self._fetch_commits_subprocess(repo_path, branch_name, limit)

    def _fetch_commits_subprocess(
        self, repo_path: str, branch_name: str, limit: int
    ) -> List[Dict[str, Any]]:
        """Fetch commits using git subprocess as fallback."""
        try:
            log = subprocess.run(
                [
                    "git",
                    "log",
                    "-n",
                    str(limit),
                    "--date=iso",
                    "--format=%H|%s|%an|%ae|%ad",
                    branch_name,
                ],
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=10,
            )

            commits = []
            if log.returncode == 0 and log.stdout:
                for line in log.stdout.splitlines():
                    parts = line.split("|", 4)
                    if len(parts) >= 5:
                        commits.append(
                            {
                                "hash": parts[0],
                                "short_hash": parts[0][:8],
                                "message": parts[1],
                                "author": {
                                    "name": parts[2],
                                    "email": parts[3],
                                },
                                "date": parts[4],
                                "files_changed": 0,
                            }
                        )

            return commits

        except Exception as e:
            logger.error("Subprocess git log failed: %s", e)
            return []

    def get_file_history(
        self,
        repo_id: int,
        repo_path: str,
        file_path: str,
        branch_name: str = "HEAD",
        from_commit: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get commit history for a specific file with caching."""
        cache_cfg = self._get_cache_config()

        cache_key_parts = ["file_history", branch_name, file_path]
        if from_commit:
            cache_key_parts.append(from_commit)
        cache_key = self._build_cache_key(repo_id, *cache_key_parts)

        if cache_cfg.get("enabled", True):
            cached_history = self._cache.get(cache_key)
            if cached_history is not None:
                logger.debug(
                    "Cache hit for file history: repo %s, file %s", repo_id, file_path
                )
                return cached_history

        logger.debug(
            "Cache miss for file history: repo %s, file %s", repo_id, file_path
        )

        try:
            repo = Repo(repo_path)
            history_commits = []

            commit_range = from_commit if from_commit else branch_name
            for commit in repo.iter_commits(commit_range, paths=file_path):
                commit_dict = commit_to_dict(commit)

                try:
                    if commit.parents:
                        parent = commit.parents[0]
                        diff = parent.diff(commit, paths=file_path)
                        if diff:
                            change_type = diff[0].change_type
                            commit_dict["change_type"] = change_type
                        else:
                            commit_dict["change_type"] = "modified"
                    else:
                        commit_dict["change_type"] = "added"
                except Exception:
                    commit_dict["change_type"] = "modified"

                history_commits.append(commit_dict)

            if cache_cfg.get("enabled", True):
                ttl = int(cache_cfg.get("ttl_seconds", 600))
                self._cache.set(cache_key, history_commits, ttl)
                logger.debug(
                    "Cached %s commits for file %s in repo %s",
                    len(history_commits),
                    file_path,
                    repo_id,
                )

            return history_commits

        except Exception as e:
            logger.error("Failed to get file history for %s: %s", file_path, e)
            return []

    def get_commit_details(
        self, repo_id: int, repo_path: str, commit_hash: str
    ) -> Optional[Dict[str, Any]]:
        """Get detailed information for a specific commit with caching."""
        cache_cfg = self._get_cache_config()
        cache_key = self._build_cache_key(repo_id, "commit", commit_hash)

        if cache_cfg.get("enabled", True):
            cached_commit = self._cache.get(cache_key)
            if cached_commit is not None:
                logger.debug("Cache hit for commit details: %s", commit_hash)
                return cached_commit

        try:
            repo = Repo(repo_path)
            commit = repo.commit(commit_hash)

            commit_dict = commit_to_dict(commit)

            stats = commit.stats.total
            commit_dict["stats"] = {
                "additions": stats.get("insertions", 0),
                "deletions": stats.get("deletions", 0),
                "changes": stats.get("lines", 0),
                "total_lines": stats.get("files", 0),
            }

            if cache_cfg.get("enabled", True):
                ttl = int(cache_cfg.get("ttl_seconds", 600))
                self._cache.set(cache_key, commit_dict, ttl)

            return commit_dict

        except Exception as e:
            logger.error("Failed to get commit details for %s: %s", commit_hash, e)
            return None

    def invalidate_repo(self, repo_id: int) -> None:
        """Invalidate all cached data for a repository."""
        try:
            pattern = f"repo:{repo_id}:*"
            logger.info("Invalidating cache for repo %s", repo_id)

            if hasattr(self._cache, "delete_pattern"):
                self._cache.delete_pattern(pattern)
            else:
                logger.warning(
                    "Cache service doesn't support pattern deletion. Cache for repo %s will expire based on TTL.",
                    repo_id,
                )

        except Exception as e:
            logger.error("Failed to invalidate cache for repo %s: %s", repo_id, e)

    def invalidate_all(self) -> None:
        """Invalidate all git-related cached data."""
        try:
            pattern = "repo:*"
            logger.warning("Invalidating ALL git caches")

            if hasattr(self._cache, "delete_pattern"):
                self._cache.delete_pattern(pattern)
            elif hasattr(self._cache, "clear"):
                self._cache.clear()
            else:
                logger.warning("Cache service doesn't support bulk deletion")

        except Exception as e:
            logger.error("Failed to invalidate all caches: %s", e)
