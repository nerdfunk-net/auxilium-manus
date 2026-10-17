"""Filesystem-backed artifact storage for workflow run content."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from pathlib import Path
from uuid import uuid4

from models.workflow_context import ArtifactRef, now_iso
from services.artifacts.artifact_service import ArtifactService
from services.artifacts.scrub import scrub_for_storage

logger = logging.getLogger(__name__)

ContentType = str | bytes

# An artifact younger than this is never purged as an orphan: its run may have been created
# after the retention sweep took its snapshot of run uuids.
_ORPHAN_GRACE_SECONDS = 3600


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
        text = scrub_for_storage(kind, text)
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
        # Each file is written to a temporary name and renamed, so the meta file (which the
        # retention sweep and readers trust) appears complete or not at all.
        content_path = self._content_path(artifact_id)
        meta_path = self._meta_path(artifact_id)
        for target, payload in ((content_path, text), (meta_path, json.dumps(meta))):
            tmp = target.with_name(target.name + ".tmp")
            tmp.write_text(payload, encoding="utf-8")
            os.replace(tmp, target)

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
        try:
            return json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("Corrupt artifact meta file, treating as unreadable: %s", meta_path)
            return None

    def get_for_run(self, *, run_uuid: str, artifact_id: str) -> tuple[ArtifactRef, str]:
        meta = self.read_meta(artifact_id)
        if meta is None or meta.get("run_id") != run_uuid:
            raise ArtifactNotFoundError(f"Artifact {artifact_id!r} not found for run {run_uuid!r}")
        ref = ArtifactRef(
            artifact_id=artifact_id,
            kind=str(meta["kind"]),
            media_type=str(meta.get("media_type", "text/plain")),
            size_bytes=meta.get("size_bytes"),
            sha256=meta.get("sha256"),
            created_at=str(meta.get("created_at", now_iso())),
        )
        return ref, self.read_content(artifact_id)

    def delete_artifact(self, artifact_id: str) -> None:
        self._content_path(artifact_id).unlink(missing_ok=True)
        self._meta_path(artifact_id).unlink(missing_ok=True)

    def _artifact_id_from_meta_path(self, meta_path: Path) -> str:
        return meta_path.name.removesuffix(".meta.json")

    def delete_for_run(self, run_uuid: str) -> int:
        """Delete every artifact whose stored meta belongs to ``run_uuid``."""
        return self.delete_for_runs({run_uuid})

    def delete_for_runs(self, run_uuids: set[str]) -> int:
        """Delete every artifact of the given runs, in one pass over the store."""
        if not run_uuids:
            return 0
        deleted = 0
        for meta_path in self._artifacts_dir.glob("*.meta.json"):
            artifact_id = self._artifact_id_from_meta_path(meta_path)
            meta = self.read_meta(artifact_id)
            if meta is not None and meta.get("run_id") in run_uuids:
                self.delete_artifact(artifact_id)
                deleted += 1
        logger.debug("Deleted %s artifact(s) for %s run(s)", deleted, len(run_uuids))
        return deleted

    def purge_orphaned(self, valid_run_uuids: set[str], *, now: float | None = None) -> int:
        """Delete artifacts whose ``run_id`` no longer matches an existing run.

        Also removes artifacts with unreadable/corrupt meta files, since their
        content can no longer be attributed to any run. Artifacts younger than the grace
        period are kept: they may belong to a run created after ``valid_run_uuids`` was read.
        """
        cutoff = (time.time() if now is None else now) - _ORPHAN_GRACE_SECONDS
        deleted = 0
        for meta_path in self._artifacts_dir.glob("*.meta.json"):
            try:
                if meta_path.stat().st_mtime > cutoff:
                    continue
            except FileNotFoundError:
                logger.debug("Artifact meta vanished during purge: %s", meta_path)
                continue  # deleted by a concurrent run delete
            artifact_id = self._artifact_id_from_meta_path(meta_path)
            meta = self.read_meta(artifact_id)
            if meta is None or meta.get("run_id") not in valid_run_uuids:
                self.delete_artifact(artifact_id)
                deleted += 1
        logger.info("Purged %s orphaned artifact(s)", deleted)
        return deleted
