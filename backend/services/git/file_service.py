"""Git file read operations — listing, search, history, and content retrieval."""

from __future__ import annotations

import csv
import fnmatch
import io
import logging
import os
from typing import Any, Dict, Optional

import yaml
from fastapi import HTTPException, status
from git import GitCommandError, InvalidGitRepositoryError

from services.git.paths import repo_path as git_repo_path
from services.git.shared_utils import get_git_repo_by_id, git_repo_manager

logger = logging.getLogger(__name__)


class GitFileService:
    """Read-only operations on files within a managed Git repository."""

    def search_files(
        self,
        repo_id: int,
        query: str = "",
        limit: int = 50,
    ) -> Dict[str, Any]:
        """Scan directory, filter by query, sort by relevance, paginate."""
        try:
            repository = git_repo_manager.get_repository(repo_id)
            if not repository:
                raise HTTPException(status_code=404, detail="Repository not found")

            repo_path = str(git_repo_path(repository))

            if not os.path.exists(repo_path):
                return {
                    "success": True,
                    "data": {
                        "files": [],
                        "total_count": 0,
                        "filtered_count": 0,
                        "query": query,
                        "repository_name": repository["name"],
                    },
                }

            structured_files = []

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

            filtered_files = structured_files
            if query:
                query_lower = query.lower()
                filtered_files = []

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

            if query:

                def sort_key(item):
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

            paginated_files = filtered_files[:limit]

            return {
                "success": True,
                "data": {
                    "files": paginated_files,
                    "total_count": len(structured_files),
                    "filtered_count": len(filtered_files),
                    "query": query,
                    "repository_name": repository["name"],
                    "has_more": len(filtered_files) > limit,
                },
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error("Error searching repository files: %s", e)
            return {"success": False, "message": "File search failed: %s" % str(e)}

    def get_commit_files(
        self,
        repo_id: int,
        commit_hash: str,
        file_path: Optional[str] = None,
    ) -> Any:
        """List files in a commit, or return single file content when file_path given."""
        try:
            repo = get_git_repo_by_id(repo_id)
            commit = repo.commit(commit_hash)

            if file_path:
                try:
                    file_content = (
                        (commit.tree / file_path).data_stream.read().decode("utf-8")
                    )
                    return {
                        "file_path": file_path,
                        "content": file_content,
                        "commit": commit_hash[:8],
                    }
                except KeyError:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="File '%s' not found in commit %s"
                        % (file_path, commit_hash[:8]),
                    )

            files = []
            for item in commit.tree.traverse():
                if item.type == "blob":
                    files.append(item.path)

            from config import settings

            config_extensions = settings.allowed_file_extensions
            config_files = [
                f for f in files if any(f.endswith(ext) for ext in config_extensions)
            ]
            return sorted(config_files)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get files: %s" % str(e),
            )

    def get_file_last_commit(
        self,
        repo_id: int,
        file_path: str,
    ) -> Dict[str, Any]:
        """Return the most recent commit metadata for a file."""
        try:
            repo = get_git_repo_by_id(repo_id)
            commits = list(repo.iter_commits(paths=file_path, max_count=1))

            if not commits:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="No commits found for file: %s" % file_path,
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
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get file history: %s" % str(e),
            )

    def get_file_history(
        self,
        repo_id: int,
        file_path: str,
        from_commit: Optional[str] = None,
        cache_service=None,
        cache_enabled: bool = True,
        cache_ttl: int = 600,
    ) -> Dict[str, Any]:
        """Return full commit chain for a file back to its creation."""
        try:
            repo = get_git_repo_by_id(repo_id)

            repo_scope = "repo:%s" % repo_id
            cache_key = "%s:filehistory:%s:%s" % (
                repo_scope,
                from_commit or "HEAD",
                file_path,
            )
            if cache_enabled and cache_service:
                cached = cache_service.get(cache_key)
                if cached is not None:
                    return cached

            start_commit = from_commit if from_commit else "HEAD"
            commits = list(repo.iter_commits(start_commit, paths=file_path))

            if not commits:
                try:
                    head_commit = repo.head.commit
                    head_commit.tree[file_path]
                    commits = list(repo.iter_commits("HEAD", paths=file_path))
                    if not commits:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            detail="No commits found for file: %s" % file_path,
                        )
                except (KeyError, AttributeError):
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="File not found: %s" % file_path,
                    )

            history_commits = []

            selected_commit_found = False
            if from_commit:
                for commit in commits:
                    if (
                        commit.hexsha == from_commit
                        or commit.hexsha.startswith(from_commit)
                        or from_commit.startswith(commit.hexsha)
                    ):
                        selected_commit_found = True
                        break

            if from_commit and not selected_commit_found:
                try:
                    commit_obj = repo.commit(from_commit)
                    try:
                        commit_obj.tree[file_path]
                        history_commits.append(
                            {
                                "hash": commit_obj.hexsha,
                                "short_hash": commit_obj.hexsha[:8],
                                "message": commit_obj.message.strip(),
                                "author": {
                                    "name": commit_obj.author.name,
                                    "email": commit_obj.author.email,
                                },
                                "date": commit_obj.committed_datetime.isoformat(),
                                "change_type": "N",
                            }
                        )
                    except KeyError:
                        pass
                except Exception:
                    pass

            for i, commit in enumerate(commits):
                change_type = "M"

                if i == len(commits) - 1:
                    change_type = "A"
                else:
                    try:
                        commit.tree[file_path]
                    except KeyError:
                        change_type = "D"

                history_commits.append(
                    {
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
                )

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
                detail="Git repository not found or commit not found: %s" % str(e),
            )
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Git file complete history error: %s" % str(e),
            )

    def get_file_content(
        self,
        repo_id: int,
        path: str,
        username: Optional[str] = None,
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
                    detail="Repository directory not found: %s" % repo_path,
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
                    detail="File not found: %s" % path,
                )

            if not os.path.isfile(file_path_resolved):
                raise HTTPException(
                    status_code=400,
                    detail="Path is not a file: %s" % path,
                )

            try:
                with open(file_path_resolved, encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=400,
                    detail="File is not a text file: %s" % path,
                )

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
            logger.error("Error reading file content: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error reading file content: %s" % str(e),
            )

    def get_file_content_parsed(
        self,
        repo_id: int,
        path: str,
        username: Optional[str] = None,
    ) -> Dict[str, Any]:
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
                raise HTTPException(status_code=404, detail="File not found: %s" % path)

            if not os.path.isfile(file_path_resolved):
                raise HTTPException(
                    status_code=400, detail="Path is not a file: %s" % path
                )

            try:
                with open(file_path_resolved, encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=400,
                    detail="File is not a text file: %s" % path,
                )

            try:
                parsed = yaml.safe_load(content)
            except yaml.YAMLError as e:
                raise HTTPException(
                    status_code=400,
                    detail="YAML parse error: %s" % str(e),
                )

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
            logger.error("Error parsing YAML file content: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error parsing file content: %s" % str(e),
            )

    def get_directory_tree(
        self,
        repo_id: int,
        path: str = "",
    ) -> Dict[str, Any]:
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
                    detail="Path not found: %s" % path,
                )

            if not os.path.isdir(target_path_resolved):
                raise HTTPException(
                    status_code=400,
                    detail="Path is not a directory: %s" % path,
                )

            def build_tree(dir_path: str, rel_path: str = "") -> dict:
                children = []

                try:
                    items = os.listdir(dir_path)
                except PermissionError:
                    logger.warning(
                        "Permission denied accessing directory: %s", dir_path
                    )
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
            logger.error("Error building directory tree: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error building directory tree: %s" % str(e),
            )

    def get_directory_files(
        self,
        repo_id: int,
        path: str = "",
    ) -> Dict[str, Any]:
        """Return flat list of files in a specific directory."""
        try:
            repository = git_repo_manager.get_repository(repo_id)
            if not repository:
                raise HTTPException(status_code=404, detail="Repository not found")

            repo = get_git_repo_by_id(repo_id)
            repo_path = str(git_repo_path(repository))

            if not os.path.exists(repo_path):
                return {
                    "path": path,
                    "files": [],
                    "directory_exists": False,
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
                return {
                    "path": path,
                    "files": [],
                    "directory_exists": False,
                }

            if not os.path.isdir(target_path_resolved):
                raise HTTPException(
                    status_code=400,
                    detail="Path is not a directory: %s" % path,
                )

            files_data = []

            try:
                items = os.listdir(target_path_resolved)
            except PermissionError:
                raise HTTPException(
                    status_code=403,
                    detail="Permission denied accessing directory",
                )

            for item in items:
                if item.startswith("."):
                    continue

                item_path = os.path.join(target_path_resolved, item)

                if not os.path.isfile(item_path):
                    continue

                file_size = os.path.getsize(item_path)
                file_rel_path = os.path.join(path, item) if path else item

                try:
                    commits = list(repo.iter_commits(paths=file_rel_path, max_count=1))

                    if commits:
                        last_commit = commits[0]
                        commit_info = {
                            "hash": last_commit.hexsha,
                            "short_hash": last_commit.hexsha[:8],
                            "message": last_commit.message.strip(),
                            "author": {
                                "name": last_commit.author.name,
                                "email": last_commit.author.email,
                            },
                            "date": last_commit.committed_datetime.isoformat(),
                            "timestamp": int(
                                last_commit.committed_datetime.timestamp()
                            ),
                        }
                    else:
                        commit_info = {
                            "hash": "",
                            "short_hash": "",
                            "message": "No commit history",
                            "author": {"name": "", "email": ""},
                            "date": "",
                            "timestamp": 0,
                        }
                except Exception as e:
                    logger.warning(
                        "Failed to get commit info for %s: %s", file_rel_path, e
                    )
                    commit_info = {
                        "hash": "",
                        "short_hash": "",
                        "message": "Error fetching commit",
                        "author": {"name": "", "email": ""},
                        "date": "",
                        "timestamp": 0,
                    }

                files_data.append(
                    {
                        "name": item,
                        "path": file_rel_path,
                        "size": file_size,
                        "last_commit": commit_info,
                    }
                )

            files_data.sort(key=lambda x: x["name"].lower())

            return {
                "path": path,
                "files": files_data,
                "directory_exists": True,
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error("Error listing directory files: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error listing directory files: %s" % str(e),
            )

    def list_csv_files(
        self,
        repo_id: int,
        query: str = "",
        limit: int = 200,
    ) -> Dict[str, Any]:
        """Return all CSV files found in a repository's working directory."""
        try:
            repository = git_repo_manager.get_repository(repo_id)
            if not repository:
                raise HTTPException(status_code=404, detail="Repository not found")

            repo_path = str(git_repo_path(repository))

            if not os.path.exists(repo_path):
                return {"success": True, "data": {"files": [], "total_count": 0}}

            csv_files = []
            for root, _dirs, files in os.walk(repo_path):
                if ".git" in root:
                    continue
                rel_root = os.path.relpath(root, repo_path)
                if rel_root == ".":
                    rel_root = ""
                for file in files:
                    if not file.lower().endswith(".csv"):
                        continue
                    if file.startswith("."):
                        continue
                    full_path = os.path.join(rel_root, file) if rel_root else file
                    abs_path = os.path.join(root, file)
                    csv_files.append(
                        {
                            "name": file,
                            "path": full_path,
                            "directory": rel_root,
                            "size": os.path.getsize(abs_path)
                            if os.path.exists(abs_path)
                            else 0,
                        }
                    )

            if query:
                q = query.lower()
                csv_files = [
                    f
                    for f in csv_files
                    if q in f["name"].lower() or q in f["path"].lower()
                ]

            csv_files.sort(key=lambda x: x["path"])
            total = len(csv_files)
            return {
                "success": True,
                "data": {"files": csv_files[:limit], "total_count": total},
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error("Error listing CSV files: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error listing CSV files: %s" % str(e),
            )

    def get_csv_headers(
        self,
        repo_id: int,
        path: str,
        delimiter: str = ",",
        quote_char: str = '"',
    ) -> Dict[str, Any]:
        """Return the header row of a CSV file from the working directory."""
        try:
            repository = git_repo_manager.get_repository(repo_id)
            if not repository:
                raise HTTPException(status_code=404, detail="Repository not found")

            repo_path_str = str(git_repo_path(repository))

            if not os.path.exists(repo_path_str):
                raise HTTPException(
                    status_code=404, detail="Repository directory not found"
                )

            file_path = os.path.join(repo_path_str, path)
            file_path_resolved = os.path.realpath(file_path)
            repo_path_resolved = os.path.realpath(repo_path_str)

            if not file_path_resolved.startswith(repo_path_resolved):
                raise HTTPException(
                    status_code=403, detail="Access denied: path is outside repository"
                )

            if not os.path.exists(file_path_resolved):
                raise HTTPException(status_code=404, detail="File not found: %s" % path)

            if not os.path.isfile(file_path_resolved):
                raise HTTPException(
                    status_code=400, detail="Path is not a file: %s" % path
                )

            try:
                with open(file_path_resolved, encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=400, detail="File is not a text file: %s" % path
                )

            reader = csv.reader(
                io.StringIO(content),
                delimiter=delimiter,
                quotechar=quote_char,
            )
            headers = []
            for row in reader:
                if row:
                    headers = [h.strip() for h in row]
                    break

            return {"success": True, "headers": headers}

        except HTTPException:
            raise
        except Exception as e:
            logger.error("Error reading CSV headers: %s", e)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error reading CSV headers: %s" % str(e),
            )
