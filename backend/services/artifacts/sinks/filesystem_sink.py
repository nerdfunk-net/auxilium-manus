"""Filesystem export sink for store-artifact."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from pathlib import Path

from services.artifacts.sinks.base import ArtifactSink, StoredExport

logger = logging.getLogger(__name__)


class FilesystemArtifactSink(ArtifactSink):
    """Write exports under ``{base_dir}/exports/{workflow_id}/{run_id}/``."""

    def __init__(self, base_dir: Path, *, output_subdirectory: str = "exports") -> None:
        self._base_dir = base_dir
        self._output_subdirectory = output_subdirectory.strip("/\\") or "exports"

    @property
    def destination(self) -> str:
        return "filesystem"

    def _run_root(self, *, workflow_id: str, run_id: str) -> Path:
        return self._base_dir / self._output_subdirectory / workflow_id / run_id

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
