"""Git CSV file helpers — listing CSV paths and reading headers."""

from __future__ import annotations

import csv
import io
import logging
import os
from typing import Any

from fastapi import HTTPException, status

from services.git.paths import repo_path as git_repo_path
from services.git.shared_utils import git_repo_manager

logger = logging.getLogger(__name__)


class GitCsvService:
    """CSV-specific read helpers for managed Git repositories."""

    def list_csv_files(
        self,
        repo_id: int,
        query: str = "",
        limit: int = 200,
    ) -> dict[str, Any]:
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
                detail=f"Error listing CSV files: {str(e)}",
            ) from e

    def get_csv_headers(
        self,
        repo_id: int,
        path: str,
        delimiter: str = ",",
        quote_char: str = '"',
    ) -> dict[str, Any]:
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
                raise HTTPException(status_code=404, detail=f"File not found: {path}")

            if not os.path.isfile(file_path_resolved):
                raise HTTPException(
                    status_code=400, detail=f"Path is not a file: {path}"
                )

            try:
                with open(file_path_resolved, encoding="utf-8") as f:
                    content = f.read()
            except UnicodeDecodeError:
                raise HTTPException(
                    status_code=400, detail=f"File is not a text file: {path}"
                ) from None

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
                detail=f"Error reading CSV headers: {str(e)}",
            ) from e
