"""Git file read operations — listing, search, history, and content retrieval."""

from __future__ import annotations

import fnmatch
import logging
import os
from typing import Any

import yaml
from git import GitCommandError, InvalidGitRepositoryError

from core.domain_exceptions import (
    DomainError,
    NotFoundError,
    ValidationFailedError,
)
from core.safe_http_errors import raise_internal_server_error
from services.git.paths import repo_path as git_repo_path
from services.git.paths import resolve_within_repo
from services.git.repository_service import GitRepositoryService
from services.git.shared_utils import get_git_repo_by_id

logger = logging.getLogger(__name__)


def _empty_file_search_data(query: str, repository_name: str) -> dict[str, Any]:
    return {
        "files": [],
        "total_count": 0,
        "filtered_count": 0,
        "query": query,
        "repository_name": repository_name,
    }


def _walk_repository_files(repo_path: str) -> list[dict[str, Any]]:
    structured_files: list[dict[str, Any]] = []

    for root, _dirs, files in os.walk(repo_path):
        if ".git" in root:
            continue

        rel_root = os.path.relpath(root, repo_path)
        if rel_root == ".":
            rel_root = ""

        for file in files:
            if file.startswith("."):
                continue

            full_path = os.path.join(rel_root, file) if rel_root else file
            file_info = {
                "name": file,
                "path": full_path,
                "directory": rel_root,
                "size": os.path.getsize(os.path.join(root, file))
                if os.path.exists(os.path.join(root, file))
                else 0,
            }
            structured_files.append(file_info)

    return structured_files


def _filter_files_by_query(
    structured_files: list[dict[str, Any]], query: str
) -> list[dict[str, Any]]:
    if not query:
        return structured_files

    query_lower = query.lower()
    filtered_files: list[dict[str, Any]] = []

    for file_info in structured_files:
        if (
            query_lower in file_info["name"].lower()
            or query_lower in file_info["path"].lower()
            or query_lower in file_info["directory"].lower()
        ):
            filtered_files.append(file_info)
        elif fnmatch.fnmatch(
            file_info["name"].lower(), f"*{query_lower}*"
        ) or fnmatch.fnmatch(file_info["path"].lower(), f"*{query_lower}*"):
            filtered_files.append(file_info)

    return filtered_files


def _sort_files_for_search(filtered_files: list[dict[str, Any]], query: str) -> None:
    if query:

        def sort_key(item: dict[str, Any]) -> tuple[int, str]:
            name_lower = item["name"].lower()
            item["path"].lower()
            query_lower = query.lower()

            if name_lower == query_lower:
                return (0, item["path"])
            elif name_lower.startswith(query_lower):
                return (1, item["path"])
            elif query_lower in name_lower:
                return (2, item["path"])
            else:
                return (3, item["path"])

        filtered_files.sort(key=sort_key)
    else:
        filtered_files.sort(key=lambda x: x["path"])


def _file_search_success(
    *,
    files: list[dict[str, Any]],
    total_count: int,
    filtered_count: int,
    query: str,
    repository_name: str,
    has_more: bool,
) -> dict[str, Any]:
    return {
        "files": files,
        "total_count": total_count,
        "filtered_count": filtered_count,
        "query": query,
        "repository_name": repository_name,
        "has_more": has_more,
    }


def _resolve_directory_listing_path(repo_path: str, path: str) -> str | None:
    target_path_resolved = str(resolve_within_repo(repo_path, path))

    if not os.path.exists(target_path_resolved):
        return None

    if not os.path.isdir(target_path_resolved):
        raise ValidationFailedError(f"Path is not a directory: {path}")

    return target_path_resolved


def _empty_commit_info(message: str) -> dict[str, Any]:
    return {
        "hash": "",
        "short_hash": "",
        "message": message,
        "author": {"name": "", "email": ""},
        "date": "",
        "timestamp": 0,
    }


def _file_last_commit_info(repo, file_rel_path: str) -> dict[str, Any]:
    try:
        commits = list(repo.iter_commits(paths=file_rel_path, max_count=1))
        if commits:
            last_commit = commits[0]
            return {
                "hash": last_commit.hexsha,
                "short_hash": last_commit.hexsha[:8],
                "message": last_commit.message.strip(),
                "author": {
                    "name": last_commit.author.name,
                    "email": last_commit.author.email,
                },
                "date": last_commit.committed_datetime.isoformat(),
                "timestamp": int(last_commit.committed_datetime.timestamp()),
            }
        return _empty_commit_info("No commit history")
    except Exception as e:
        logger.warning("Failed to get commit info for %s: %s", file_rel_path, e)
        return _empty_commit_info("Error fetching commit")


def _list_directory_file_entries(
    *,
    repo,
    target_path: str,
    path: str,
    items: list[str],
) -> list[dict[str, Any]]:
    files_data: list[dict[str, Any]] = []
    for item in items:
        if item.startswith("."):
            continue

        item_path = os.path.join(target_path, item)
        if not os.path.isfile(item_path):
            continue

        file_rel_path = os.path.join(path, item) if path else item
        files_data.append(
            {
                "name": item,
                "path": file_rel_path,
                "size": os.path.getsize(item_path),
                "last_commit": _file_last_commit_info(repo, file_rel_path),
            }
        )

    files_data.sort(key=lambda x: x["name"].lower())
    return files_data


def _file_history_cache_key(
    repo_id: int, file_path: str, from_commit: str | None
) -> str:
    repo_scope = f"repo:{repo_id}"
    return "{}:filehistory:{}:{}".format(
        repo_scope,
        from_commit or "HEAD",
        file_path,
    )


def _resolve_commits_for_file(repo, file_path: str, start_commit: str) -> list[Any]:
    commits = list(repo.iter_commits(start_commit, paths=file_path))

    if not commits:
        try:
            head_commit = repo.head.commit
            head_commit.tree[file_path]
            commits = list(repo.iter_commits("HEAD", paths=file_path))
            if not commits:
                raise NotFoundError(f"No commits found for file: {file_path}")
        except (KeyError, AttributeError):
            raise NotFoundError(f"File not found: {file_path}") from None

    return commits


def _selected_commit_in_chain(commits: list[Any], from_commit: str) -> bool:
    for commit in commits:
        if (
            commit.hexsha == from_commit
            or commit.hexsha.startswith(from_commit)
            or from_commit.startswith(commit.hexsha)
        ):
            return True
    return False


def _history_entry_from_commit(commit: Any, change_type: str) -> dict[str, Any]:
    return {
        "hash": commit.hexsha,
        "short_hash": commit.hexsha[:8],
        "message": commit.message.strip(),
        "author": {
            "name": commit.author.name,
            "email": commit.author.email,
        },
        "date": commit.committed_datetime.isoformat(),
        "change_type": change_type,
    }


def _change_type_for_file_at_commit(
    commit: Any, file_path: str, *, is_oldest: bool
) -> str:
    if is_oldest:
        return "A"
    try:
        commit.tree[file_path]
    except KeyError:
        return "D"
    return "M"


def _maybe_prepend_selected_commit(
    repo, from_commit: str, file_path: str
) -> list[dict[str, Any]]:
    try:
        commit_obj = repo.commit(from_commit)
        try:
            commit_obj.tree[file_path]
            return [_history_entry_from_commit(commit_obj, "N")]
        except KeyError:  # noqa: S110  # file not in that commit: nothing to prepend
            pass
    except Exception:
        logger.debug("History lookup failed for %s", file_path, exc_info=True)
    return []


class GitFileService:
    """Read-only operations on files within a managed Git repository."""

    def __init__(self, repos: GitRepositoryService | None = None) -> None:
        self._repos = repos or GitRepositoryService()

    def get_file_history(
        self,
        repo_id: int,
        file_path: str,
        from_commit: str | None = None,
        cache_service=None,
        cache_enabled: bool = True,
        cache_ttl: int = 600,
    ) -> dict[str, Any]:
        """Return full commit chain for a file back to its creation."""
        try:
            repo = get_git_repo_by_id(repo_id, self._repos)
            cache_key = _file_history_cache_key(repo_id, file_path, from_commit)
            if cache_enabled and cache_service:
                cached = cache_service.get(cache_key)
                if cached is not None:
                    return cached

            start_commit = from_commit if from_commit else "HEAD"
            commits = _resolve_commits_for_file(repo, file_path, start_commit)

            history_commits: list[dict[str, Any]] = []
            if from_commit and not _selected_commit_in_chain(commits, from_commit):
                history_commits.extend(
                    _maybe_prepend_selected_commit(repo, from_commit, file_path)
                )

            for i, commit in enumerate(commits):
                change_type = _change_type_for_file_at_commit(
                    commit, file_path, is_oldest=(i == len(commits) - 1)
                )
                history_commits.append(_history_entry_from_commit(commit, change_type))

            result = {
                "file_path": file_path,
                "from_commit": start_commit,
                "total_commits": len(history_commits),
                "commits": history_commits,
            }
            if cache_enabled and cache_service:
                cache_service.set(cache_key, result, cache_ttl)
            return result

        except (InvalidGitRepositoryError, GitCommandError) as e:
            logger.warning("Git repository or commit not found: %s", e, exc_info=True)
            raise NotFoundError("Git repository or commit not found") from e
        except Exception as e:
            raise_internal_server_error(logger, "Git file complete history error", e)

    def get_file_content_parsed(
        self,
        repo_id: int,
        path: str,
        username: str | None = None,
    ) -> dict[str, Any]:
        """Return file content and its parsed representation (YAML)."""
        try:
            repository = self._repos.get_repository(repo_id)
            if not repository:
                raise NotFoundError("Repository not found")

            repo_path = git_repo_path(repository)

            if not os.path.exists(repo_path):
                raise NotFoundError("Repository directory not found")

            file_path_resolved = str(resolve_within_repo(repo_path, path))

            if not os.path.exists(file_path_resolved):
                raise NotFoundError(f"File not found: {path}")

            if not os.path.isfile(file_path_resolved):
                raise ValidationFailedError(f"Path is not a file: {path}")

            try:
                with open(file_path_resolved, encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                raise ValidationFailedError(f"File is not a text file: {path}") from None

            try:
                parsed = yaml.safe_load(content)
            except yaml.YAMLError as e:
                logger.info("YAML parse error for %s: %s", path, e, exc_info=True)
                raise ValidationFailedError("YAML parse error") from e

            if username:
                logger.info(
                    "User %s parsed YAML file %s from repository %s",
                    username,
                    path,
                    repository["name"],
                )

            return {"parsed": parsed, "file_path": path}

        except DomainError:
            raise
        except Exception as e:
            raise_internal_server_error(logger, "Error parsing file content", e)
