"""Git export sink for store-artifact."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from services.artifacts.sinks.base import ArtifactSink, StoredExport
from services.git.paths import repo_path as get_repo_path
from workflow_steps.common.device_template import sanitize_relative_path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GitFinalizeResult:
    """Summary of optional commit/push at the end of a git export."""

    committed: bool
    pushed: bool
    commit_sha: str | None
    files_changed: int
    message: str


class GitArtifactSink(ArtifactSink):
    """Write exports into a local git working tree with optional pull/commit/push."""

    def __init__(
        self,
        repository: dict[str, Any],
        *,
        repository_subdirectory: str = "",
        pull_before_write: bool = False,
        commit_after_write: bool = False,
        push_after_write: bool = False,
    ) -> None:
        self._repository = repository
        self._repository_subdirectory = repository_subdirectory.strip("/\\")
        self._pull_before_write = pull_before_write
        self._commit_after_write = commit_after_write
        self._push_after_write = push_after_write
        self._written_paths: list[str] = []
        self._repo: Any = None
        self._lock = asyncio.Lock()

        import service_factory

        self._git_service = service_factory.build_git_service()

    @property
    def destination(self) -> str:
        return "git"

    @property
    def repository_ref(self) -> str:
        return str(self._repository.get("source_id") or self._repository.get("id") or "")

    @property
    def has_writes(self) -> bool:
        return bool(self._written_paths)

    def _repo_root(self) -> Path:
        return get_repo_path(self._repository)

    def _repo_relative_path(self, relative_path: str) -> str:
        parts: list[str] = []
        if self._repository_subdirectory:
            parts.append(self._repository_subdirectory)
        parts.append(relative_path.lstrip("/\\"))
        combined = "/".join(parts)
        return sanitize_relative_path(combined)

    async def prepare(self) -> None:
        """Open or clone the repository and optionally pull latest changes."""

        def _prepare_sync() -> Any:
            repo = self._git_service.open_or_clone(self._repository)
            if self._pull_before_write:
                pull_result = self._git_service.pull(self._repository, repo=repo)
                if not pull_result.success:
                    raise RuntimeError(pull_result.message)
            return repo

        async with self._lock:
            self._repo = await asyncio.to_thread(_prepare_sync)

    async def write_text(
        self,
        *,
        relative_path: str,
        content: str,
        workflow_id: str,
        run_id: str,
    ) -> StoredExport:
        del workflow_id, run_id
        async with self._lock:
            return await asyncio.to_thread(
                self._write_text_sync,
                relative_path,
                content,
            )

    def _write_text_sync(self, relative_path: str, content: str) -> StoredExport:
        if self._repo is None:
            raise RuntimeError("Git export sink is not prepared; call prepare() first")

        repo_relative = self._repo_relative_path(relative_path)
        normalized = Path(repo_relative)
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError(f"Unsafe export path: {relative_path!r}")

        target = self._repo_root() / normalized
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()

        if repo_relative not in self._written_paths:
            self._written_paths.append(repo_relative)

        logger.info(
            "Exported artifact to git repo=%s path=%s bytes=%d",
            self._repository.get("name"),
            target,
            len(content.encode("utf-8")),
        )
        return StoredExport(
            destination=self.destination,
            path=str(target),
            size_bytes=len(content.encode("utf-8")),
            sha256=digest,
        )

    async def finalize(self, commit_message: str) -> GitFinalizeResult | None:
        """Commit and/or push files written during this step."""
        if not self._written_paths:
            return None
        if not self._commit_after_write and not self._push_after_write:
            return None

        async with self._lock:
            return await asyncio.to_thread(self._finalize_sync, commit_message)

    def _finalize_sync(self, commit_message: str) -> GitFinalizeResult:
        if self._repo is None:
            raise RuntimeError("Git export sink is not prepared; call prepare() first")

        commit_sha: str | None = None
        files_changed = 0
        committed = False
        pushed = False
        messages: list[str] = []

        if self._commit_after_write:
            commit_result = self._git_service.commit(
                self._repository,
                message=commit_message,
                files=self._written_paths,
                repo=self._repo,
            )
            if not commit_result.success:
                raise RuntimeError(commit_result.message)
            commit_sha = commit_result.commit_sha
            files_changed = commit_result.files_changed
            committed = files_changed > 0
            messages.append(commit_result.message)

        if self._push_after_write:
            if self._commit_after_write and files_changed == 0:
                messages.append("Skipped push because there were no changes to commit")
            else:
                push_result = self._git_service.push(self._repository, repo=self._repo)
                if not push_result.success:
                    raise RuntimeError(push_result.message)
                pushed = push_result.pushed
                messages.append(push_result.message)

        return GitFinalizeResult(
            committed=committed,
            pushed=pushed,
            commit_sha=commit_sha,
            files_changed=files_changed,
            message="; ".join(messages) if messages else "No git commit or push performed",
        )
