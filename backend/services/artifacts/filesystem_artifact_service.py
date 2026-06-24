"""Filesystem-backed artifact storage for workflow run content."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Union
from uuid import uuid4

from models.workflow_context import ArtifactRef, now_iso
from services.artifacts.artifact_service import ArtifactService

logger = logging.getLogger(__name__)

ContentType = Union[str, bytes]


class ArtifactNotFoundError(FileNotFoundError):
    """Raised when an artifact id does not exist or does not belong to a run."""


class FilesystemArtifactService(ArtifactService):
    """Persist artifact bytes on disk under ``{base_dir}/artifacts/``."""

    def __init__(self, base_dir: Path) -> None:
        self._artifacts_dir = base_dir / "artifacts"
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)

    def _content_path(self, artifact_id: str) -> Path:
        return self._artifacts_dir / f"{artifact_id}.content"

    def _meta_path(self, artifact_id: str) -> Path:
        return self._artifacts_dir / f"{artifact_id}.meta.json"

    async def store(
        self,
        *,
        content: ContentType,
        kind: str,
        device_id: str,
        run_id: str,
        media_type: str = "text/plain",
    ) -> ArtifactRef:
        text = content.decode("utf-8") if isinstance(content, bytes) else content
        artifact_id = str(uuid4())
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        ref = ArtifactRef(
            artifact_id=artifact_id,
            kind=kind,
            media_type=media_type,
            size_bytes=len(text.encode("utf-8")),
            sha256=digest,
        )
        meta = {
            "artifact_id": artifact_id,
            "kind": kind,
            "media_type": media_type,
            "size_bytes": ref.size_bytes,
            "sha256": digest,
            "created_at": ref.created_at,
            "run_id": run_id,
            "device_id": device_id,
        }
        await asyncio.to_thread(
            self._write_files,
            artifact_id,
            text,
            meta,
        )
        logger.debug(
            "Stored artifact artifact_id=%s kind=%s run_id=%s device_id=%s",
            artifact_id,
            kind,
            run_id,
            device_id,
        )
        return ref

    def _write_files(self, artifact_id: str, text: str, meta: dict) -> None:
        content_path = self._content_path(artifact_id)
        meta_path = self._meta_path(artifact_id)
        content_path.write_text(text, encoding="utf-8")
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

    async def resolve(self, ref: ArtifactRef) -> str:
        return await asyncio.to_thread(self.read_content, ref.artifact_id)

    def read_content(self, artifact_id: str) -> str:
        content_path = self._content_path(artifact_id)
        if not content_path.is_file():
            raise ArtifactNotFoundError(f"Artifact not found: {artifact_id}")
        return content_path.read_text(encoding="utf-8")

    def read_meta(self, artifact_id: str) -> dict | None:
        meta_path = self._meta_path(artifact_id)
        if not meta_path.is_file():
            return None
        return json.loads(meta_path.read_text(encoding="utf-8"))

    def get_for_run(self, *, run_uuid: str, artifact_id: str) -> tuple[ArtifactRef, str]:
        meta = self.read_meta(artifact_id)
        if meta is None or meta.get("run_id") != run_uuid:
            raise ArtifactNotFoundError(
                f"Artifact {artifact_id!r} not found for run {run_uuid!r}"
            )
        ref = ArtifactRef(
            artifact_id=artifact_id,
            kind=str(meta["kind"]),
            media_type=str(meta.get("media_type", "text/plain")),
            size_bytes=meta.get("size_bytes"),
            sha256=meta.get("sha256"),
            created_at=str(meta.get("created_at", now_iso())),
        )
        return ref, self.read_content(artifact_id)
