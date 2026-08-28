"""Search text inside files of a cloned Git repository (current tree + optional history)."""

from __future__ import annotations

import fnmatch
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from git import Repo

logger = logging.getLogger(__name__)

MAX_CONTENT_SEARCH_FILE_SIZE = 1024 * 1024
MAX_FILES_SCANNED = 5000
HISTORY_MAX_COMMITS = 500


@dataclass(frozen=True)
class GitContentMatch:
    """One matching file: the version searched, and where the match was found."""

    file_path: str
    content: str
    line_number: int
    line_content: str
    commit: str | None
    commit_message: str | None
    commit_date: str | None


def _resolve_within_repo(repo_root: str, rel_path: str) -> str:
    """Resolve *rel_path* against *repo_root*, rejecting anything that escapes it."""
    root = os.path.realpath(repo_root)
    candidate = os.path.realpath(os.path.join(repo_root, rel_path))
    if candidate != root and os.path.commonpath([root, candidate]) != root:
        raise ValueError(f"'{rel_path}' is outside the repository")
    return candidate


def _line_matches(line: str, query: str, case_sensitive: bool) -> bool:
    if case_sensitive:
        return query in line
    return query.lower() in line.lower()


def _first_match_in_text(content: str, query: str, case_sensitive: bool) -> tuple[int, str] | None:
    for idx, line in enumerate(content.splitlines(), start=1):
        if _line_matches(line, query, case_sensitive):
            return idx, line
    return None


class GitContentSearchService:
    """Finds files in a cloned Git repository whose content matches a text query."""

    def search(
        self,
        repo_dir: Path,
        *,
        directory: str,
        file_filter: str,
        recursive: bool,
        include_history: bool,
        search_text: str,
        case_sensitive: bool,
    ) -> tuple[list[GitContentMatch], int]:
        """Return (matches, files_scanned). One match per matching file."""
        query = search_text.strip()
        if not query:
            raise ValueError("search_text is required")

        repo_root = str(repo_dir)
        sub_path = directory.strip("/\\")
        search_root = _resolve_within_repo(repo_root, sub_path)

        candidates = self._list_candidate_files(repo_root, search_root, file_filter, recursive)

        repo: Repo | None = Repo(repo_root) if include_history else None

        matches: list[GitContentMatch] = []
        files_scanned = 0
        for rel_path in candidates:
            files_scanned += 1
            abs_path = os.path.join(repo_root, rel_path)
            content = self._read_text_file(abs_path)
            if content is not None:
                hit = _first_match_in_text(content, query, case_sensitive)
                if hit is not None:
                    line_number, line_content = hit
                    matches.append(
                        GitContentMatch(
                            file_path=rel_path,
                            content=content,
                            line_number=line_number,
                            line_content=line_content,
                            commit=None,
                            commit_message=None,
                            commit_date=None,
                        )
                    )
                    continue

            if repo is not None:
                historical = self._search_history(repo, rel_path, query, case_sensitive)
                if historical is not None:
                    matches.append(historical)

        return matches, files_scanned

    @staticmethod
    def _list_candidate_files(
        repo_root: str, search_root: str, file_filter: str, recursive: bool
    ) -> list[str]:
        if not os.path.isdir(search_root):
            return []

        pattern = file_filter.strip()
        candidates: list[str] = []
        for root, dirnames, filenames in os.walk(search_root):
            dirnames[:] = [d for d in dirnames if d != ".git" and not d.startswith(".")]

            for filename in filenames:
                if filename.startswith("."):
                    continue
                if pattern and not fnmatch.fnmatch(filename.lower(), pattern.lower()):
                    continue

                abs_path = os.path.join(root, filename)
                if not os.path.isfile(abs_path):
                    continue
                if os.path.getsize(abs_path) > MAX_CONTENT_SEARCH_FILE_SIZE:
                    continue

                candidates.append(os.path.relpath(abs_path, repo_root))
                if len(candidates) >= MAX_FILES_SCANNED:
                    return sorted(candidates)

            if not recursive:
                break

        return sorted(candidates)

    @staticmethod
    def _read_text_file(abs_path: str) -> str | None:
        try:
            with open(abs_path, encoding="utf-8") as handle:
                return handle.read()
        except (UnicodeDecodeError, OSError):
            return None

    @staticmethod
    def _read_blob_at_commit(repo: Repo, commit_hexsha: str, rel_path: str) -> str | None:
        try:
            commit = repo.commit(commit_hexsha)
            raw = (commit.tree / rel_path).data_stream.read()
            return raw.decode("utf-8")
        except (KeyError, UnicodeDecodeError, AttributeError, OSError):
            return None

    def _search_history(
        self, repo: Repo, rel_path: str, query: str, case_sensitive: bool
    ) -> GitContentMatch | None:
        try:
            commits = repo.iter_commits(paths=rel_path, max_count=HISTORY_MAX_COMMITS)
            for commit in commits:
                content = self._read_blob_at_commit(repo, commit.hexsha, rel_path)
                if content is None:
                    continue
                hit = _first_match_in_text(content, query, case_sensitive)
                if hit is None:
                    continue
                line_number, line_content = hit
                return GitContentMatch(
                    file_path=rel_path,
                    content=content,
                    line_number=line_number,
                    line_content=line_content,
                    commit=commit.hexsha[:8],
                    commit_message=commit.message.strip(),
                    commit_date=commit.committed_datetime.isoformat(),
                )
        except Exception:
            logger.warning("git-content-search: could not read history for %s", rel_path)
        return None
