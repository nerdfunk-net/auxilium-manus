"""Filesystem export sink for store-artifact."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from services.artifacts.sinks.base import ArtifactSink, StoredExport

logger = logging.getLogger(__name__)


def _sanitize_output_subdirectory(output_subdirectory: str) -> str:
    """Normalize subdirectory under the artifact base dir; reject ``..`` / absolute."""
    cleaned = (output_subdirectory or "").replace("\\", "/").strip()
    if not cleaned:
        return "exports"
    if cleaned.startswith("/") or Path(cleaned).is_absolute():
        raise ValueError(f"output_subdirectory must be a relative path: {output_subdirectory!r}")
    cleaned = cleaned.strip("/")
    parts = [part for part in cleaned.split("/") if part and part != "."]
    if not parts:
        return "exports"
    if ".." in parts:
        raise ValueError(
            f"output_subdirectory must not contain parent directory segments: "
            f"{output_subdirectory!r}"
        )
    if any(":" in part for part in parts):
        raise ValueError(f"output_subdirectory must be a relative path: {output_subdirectory!r}")
    return "/".join(parts)


class FilesystemArtifactSink(ArtifactSink):
    """Write exports under ``{base_dir}/{output_subdirectory}/{workflow_id}/{run_id}/``."""

    def __init__(self, base_dir: Path, *, output_subdirectory: str = "exports") -> None:
        self._base_dir = Path(base_dir)
        self._output_subdirectory = _sanitize_output_subdirectory(output_subdirectory)

    @property
    def destination(self) -> str:
        return "filesystem"

    def _run_root(self, *, workflow_id: str, run_id: str) -> Path:
        root = self._base_dir.resolve()
        candidate = (root / self._output_subdirectory / workflow_id / run_id).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                f"Unsafe export root escapes base_dir: {self._output_subdirectory!r}"
            ) from exc
        return candidate

    async def write_text(
        self,
        *,
        relative_path: str,
        content: str,
        workflow_id: str,
        run_id: str,
    ) -> StoredExport:
        return await asyncio.to_thread(
            self._write_text_sync,
            relative_path,
            content,
            workflow_id,
            run_id,
        )

    def _write_text_sync(
        self,
        relative_path: str,
        content: str,
        workflow_id: str,
        run_id: str,
    ) -> StoredExport:
        normalized = Path(relative_path.lstrip("/\\"))
        if normalized.is_absolute() or ".." in normalized.parts:
            raise ValueError(f"Unsafe export path: {relative_path!r}")

        target = self._run_root(workflow_id=workflow_id, run_id=run_id) / normalized
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        logger.info(
            "Exported artifact path=%s workflow_id=%s run_id=%s bytes=%d",
            target,
            workflow_id,
            run_id,
            len(content.encode("utf-8")),
        )
        return StoredExport(
            destination=self.destination,
            path=str(target),
            size_bytes=len(content.encode("utf-8")),
            sha256=digest,
        )
