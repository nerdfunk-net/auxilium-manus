"""Git file read operations — listing, search, history, and content retrieval."""

from __future__ import annotations

import fnmatch
import logging
import os
import uuid
from typing import Any

import yaml
from fastapi import HTTPException, status
from git import GitCommandError, InvalidGitRepositoryError

from core.safe_http_errors import raise_internal_server_error
from services.git.paths import repo_path as git_repo_path
from services.git.shared_utils import get_git_repo_by_id, git_repo_manager

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
    target_path = os.path.join(repo_path, path) if path else repo_path
    target_path_resolved = os.path.realpath(target_path)
    repo_path_resolved = os.path.realpath(repo_path)

    if not target_path_resolved.startswith(repo_path_resolved):
        raise HTTPException(
            status_code=403,
            detail="Access denied: path is outside repository",
        )

    if not os.path.exists(target_path_resolved):
        return None

    if not os.path.isdir(target_path_resolved):
        raise HTTPException(
            status_code=400,
            detail=f"Path is not a directory: {path}",
        )

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
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No commits found for file: {file_path}",
                )
        except (KeyError, AttributeError):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File not found: {file_path}",
            ) from None

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
        except KeyError:
            pass
    except Exception:
        pass
    return []


class GitFileService:
    """Read-only operations on files within a managed Git repository."""

    def search_files(
        self,
        repo_id: int,
        query: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        """Scan directory, filter by query, sort by relevance, paginate."""
        try:
            repository = git_repo_manager.get_repository(repo_id)
            if not repository:
                raise HTTPException(status_code=404, detail="Repository not found")

            repo_path = str(git_repo_path(repository))
            if not os.path.exists(repo_path):
                return {
                    "success": True,
                    "data": _empty_file_search_data(query, repository["name"]),
                }

            structured_files = _walk_repository_files(repo_path)
            filtered_files = _filter_files_by_query(structured_files, query)
            _sort_files_for_search(filtered_files, query)

            return {
                "success": True,
                "data": _file_search_success(
                    files=filtered_files[:limit],
                    total_count=len(structured_files),
                    filtered_count=len(filtered_files),
                    query=query,
                    repository_name=repository["name"],
                    has_more=len(filtered_files) > limit,
                ),
            }

        except HTTPException:
            raise
        except Exception:
            error_id = str(uuid.uuid4())
            logger.error(
                "Error searching repository files (error_id=%s)",
                error_id,
                exc_info=True,
                extra={"error_id": error_id},
            )
            return {
                "success": False,
                "message": "File search failed",
                "error_id": error_id,
            }

    def get_commit_files(
        self,
        repo_id: int,
        commit_hash: str,
        file_path: str | None = None,
    ) -> Any:
        """List files in a commit, or return single file content when file_path given."""
        try:
            repo = get_git_repo_by_id(repo_id)
            commit = repo.commit(commit_hash)

            if file_path:
                try:
                    file_content = (commit.tree / file_path).data_stream.read().decode("utf-8")
                    return {
                        "file_path": file_path,
                        "content": file_content,
                        "commit": commit_hash[:8],
                    }
                except KeyError:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail=f"File '{file_path}' not found in commit {commit_hash[:8]}",
                    ) from None

            files = []
            for item in commit.tree.traverse():
                if item.type == "blob":
                    files.append(item.path)

            from config import settings

            config_extensions = settings.allowed_file_extensions
            config_files = [f for f in files if any(f.endswith(ext) for ext in config_extensions)]
            return sorted(config_files)
        except HTTPException:
            raise
        except Exception as e:
            raise_internal_server_error(logger, "Failed to get files", e)

    def get_file_last_commit(
        self,
        repo_id: int,
        file_path: str,
    ) -> dict[str, Any]:
        """Return the most recent commit metadata for a file."""
        try:
            repo = get_git_repo_by_id(repo_id)
            commits = list(repo.iter_commits(paths=file_path, max_count=1))

            if not commits:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"No commits found for file: {file_path}",
                )

            last_commit = commits[0]

            try:
                (last_commit.tree / file_path).data_stream.read().decode("utf-8")
                file_exists = True
            except (KeyError, AttributeError, UnicodeDecodeError, OSError):
                file_exists = False

            return {
                "file_path": file_path,
                "file_exists": file_exists,
                "last_commit": {
                    "hash": last_commit.hexsha,
                    "short_hash": last_commit.hexsha[:8],
                    "message": last_commit.message.strip(),
                    "author": {
                        "name": last_commit.author.name,
                        "email": last_commit.author.email,
                    },
                    "committer": {
                        "name": last_commit.committer.name,
                        "email": last_commit.committer.email,
                    },
                    "date": last_commit.committed_datetime.isoformat(),
                    "timestamp": int(last_commit.committed_datetime.timestamp()),
                },
            }

        except HTTPException:
            raise
        except Exception as e:
            raise_internal_server_error(logger, "Failed to get file history", e)

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
            repo = get_git_repo_by_id(repo_id)
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
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Git repository not found or commit not found: {str(e)}",
            ) from e
        except Exception as e:
            raise_internal_server_error(logger, "Git file complete history error", e)

    def get_file_content(
        self,
        repo_id: int,
        path: str,
        username: str | None = None,
    ) -> str:
        """Return raw file content at HEAD (working directory)."""
        try:
            repository = git_repo_manager.get_repository(repo_id)
            if not repository:
                raise HTTPException(status_code=404, detail="Repository not found")

            repo_path = git_repo_path(repository)

            if not os.path.exists(repo_path):
                raise HTTPException(
                    status_code=404,
                    detail=f"Repository directory not found: {repo_path}",
                )

            file_path = os.path.join(repo_path, path)
            file_path_resolved = os.path.realpath(file_path)
            repo_path_resolved = os.path.realpath(repo_path)

            if not file_path_resolved.startswith(repo_path_resolved):
                raise HTTPException(
                    status_code=403,
                    detail="Access denied: file path is outside repository",
                )

            if not os.path.exists(file_path_resolved):
                raise HTTPException(
                    status_code=404,
                    detail=f"File not found: {path}",
                )

            if not os.path.isfile(file_path_resolved):
                raise HTTPException(
                    status_code=400,
                    detail=f"Path is not a file: {path}",
                )

            try:
                with open(file_path_resolved, encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=400,
                    detail=f"File is not a text file: {path}",
                ) from None

            if username:
                logger.info(
                    "User %s read file %s from repository %s",
                    username,
                    path,
                    repository["name"],
                )

            return content

        except HTTPException:
            raise
        except Exception as e:
            raise_internal_server_error(logger, "Error reading file content", e)

    def get_file_content_parsed(
        self,
        repo_id: int,
        path: str,
        username: str | None = None,
    ) -> dict[str, Any]:
        """Return file content and its parsed representation (YAML)."""
        try:
            repository = git_repo_manager.get_repository(repo_id)
            if not repository:
                raise HTTPException(status_code=404, detail="Repository not found")

            repo_path = git_repo_path(repository)

            if not os.path.exists(repo_path):
                raise HTTPException(
                    status_code=404,
                    detail="Repository directory not found",
                )

            file_path = os.path.join(repo_path, path)
            file_path_resolved = os.path.realpath(file_path)
            repo_path_resolved = os.path.realpath(repo_path)

            if not file_path_resolved.startswith(repo_path_resolved):
                raise HTTPException(
                    status_code=403,
                    detail="Access denied: file path is outside repository",
                )

            if not os.path.exists(file_path_resolved):
                raise HTTPException(status_code=404, detail=f"File not found: {path}")

            if not os.path.isfile(file_path_resolved):
                raise HTTPException(status_code=400, detail=f"Path is not a file: {path}")

            try:
                with open(file_path_resolved, encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=400,
                    detail=f"File is not a text file: {path}",
                ) from None

            try:
                parsed = yaml.safe_load(content)
            except yaml.YAMLError as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"YAML parse error: {str(e)}",
                ) from e

            if username:
                logger.info(
                    "User %s parsed YAML file %s from repository %s",
                    username,
                    path,
                    repository["name"],
                )

            return {"parsed": parsed, "file_path": path}

        except HTTPException:
            raise
        except Exception as e:
            raise_internal_server_error(logger, "Error parsing file content", e)

    def get_directory_tree(
        self,
        repo_id: int,
        path: str = "",
    ) -> dict[str, Any]:
        """Return nested directory tree for a commit."""
        try:
            repository = git_repo_manager.get_repository(repo_id)
            if not repository:
                raise HTTPException(status_code=404, detail="Repository not found")

            repo_path = str(git_repo_path(repository))

            if not os.path.exists(repo_path):
                return {
                    "name": "root",
                    "path": "",
                    "type": "directory",
                    "children": [],
                    "repository_name": repository["name"],
                }

            target_path = os.path.join(repo_path, path) if path else repo_path
            target_path_resolved = os.path.realpath(target_path)
            repo_path_resolved = os.path.realpath(repo_path)

            if not target_path_resolved.startswith(repo_path_resolved):
                raise HTTPException(
                    status_code=403,
                    detail="Access denied: path is outside repository",
                )

            if not os.path.exists(target_path_resolved):
                raise HTTPException(
                    status_code=404,
                    detail=f"Path not found: {path}",
                )

            if not os.path.isdir(target_path_resolved):
                raise HTTPException(
                    status_code=400,
                    detail=f"Path is not a directory: {path}",
                )

            def build_tree(dir_path: str, rel_path: str = "") -> dict:
                children = []

                try:
                    items = os.listdir(dir_path)
                except PermissionError:
                    logger.warning("Permission denied accessing directory: %s", dir_path)
                    return None

                dirs = []
                files = []

                for item in items:
                    if item.startswith("."):
                        continue

                    item_path = os.path.join(dir_path, item)
                    item_rel_path = os.path.join(rel_path, item) if rel_path else item

                    if os.path.isdir(item_path):
                        dirs.append((item, item_path, item_rel_path))
                    elif os.path.isfile(item_path):
                        files.append(item)

                dirs.sort(key=lambda x: x[0].lower())

                for _dir_name, dir_full_path, dir_rel_path in dirs:
                    subtree = build_tree(dir_full_path, dir_rel_path)
                    if subtree:
                        children.append(subtree)

                node_name = os.path.basename(dir_path) if rel_path else "root"

                return {
                    "name": node_name,
                    "path": rel_path,
                    "type": "directory",
                    "file_count": len(files),
                    "children": children,
                }

            tree = build_tree(target_path_resolved, path)

            if tree is None:
                raise HTTPException(
                    status_code=403,
                    detail="Permission denied accessing directory",
                )

            tree["repository_name"] = repository["name"]

            return tree

        except HTTPException:
            raise
        except Exception as e:
            raise_internal_server_error(logger, "Error building directory tree", e)

    def get_directory_files(
        self,
        repo_id: int,
        path: str = "",
    ) -> dict[str, Any]:
        """Return flat list of files in a specific directory."""
        try:
            repository = git_repo_manager.get_repository(repo_id)
            if not repository:
                raise HTTPException(status_code=404, detail="Repository not found")

            repo = get_git_repo_by_id(repo_id)
            repo_path = str(git_repo_path(repository))
            if not os.path.exists(repo_path):
                return {"path": path, "files": [], "directory_exists": False}

            target = _resolve_directory_listing_path(repo_path, path)
            if target is None:
                return {"path": path, "files": [], "directory_exists": False}

            try:
                items = os.listdir(target)
            except PermissionError:
                raise HTTPException(
                    status_code=403,
                    detail="Permission denied accessing directory",
                ) from None

            files_data = _list_directory_file_entries(
                repo=repo, target_path=target, path=path, items=items
            )
            return {"path": path, "files": files_data, "directory_exists": True}

        except HTTPException:
            raise
        except Exception as e:
            raise_internal_server_error(logger, "Error listing directory files", e)
