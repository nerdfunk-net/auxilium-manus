"""Tests for filesystem artifact storage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.artifacts import ArtifactNotFoundError, FilesystemArtifactService


class FilesystemArtifactServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_store_and_get_for_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = FilesystemArtifactService(Path(tmp))
            ref = await service.store(
                content="interface Gi0/0\n shutdown",
                kind="running_config",
                device_id="device-1",
                run_id="run-uuid-1",
            )
            loaded_ref, content = service.get_for_run(
                run_uuid="run-uuid-1",
                artifact_id=ref.artifact_id,
            )
            self.assertEqual(content, "interface Gi0/0\n shutdown")
            self.assertEqual(loaded_ref.kind, "running_config")

    async def test_get_for_run_rejects_wrong_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = FilesystemArtifactService(Path(tmp))
            ref = await service.store(
                content="config",
                kind="running_config",
                device_id="device-1",
                run_id="run-a",
            )
            with self.assertRaises(ArtifactNotFoundError):
                service.get_for_run(run_uuid="run-b", artifact_id=ref.artifact_id)

    async def test_delete_for_run_removes_only_matching_run_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = FilesystemArtifactService(Path(tmp))
            ref_a = await service.store(
                content="a", kind="running_config", device_id="d1", run_id="run-a"
            )
            ref_b = await service.store(
                content="b", kind="running_config", device_id="d1", run_id="run-b"
            )

            deleted = service.delete_for_run("run-a")

            self.assertEqual(deleted, 1)
            self.assertIsNone(service.read_meta(ref_a.artifact_id))
            self.assertIsNotNone(service.read_meta(ref_b.artifact_id))

    async def test_purge_orphaned_deletes_artifacts_for_missing_runs_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = FilesystemArtifactService(Path(tmp))
            live_ref = await service.store(
                content="a", kind="running_config", device_id="d1", run_id="run-live"
            )
            orphan_ref = await service.store(
                content="b", kind="running_config", device_id="d1", run_id="run-gone"
            )

            deleted = service.purge_orphaned({"run-live"})

            self.assertEqual(deleted, 1)
            self.assertIsNotNone(service.read_meta(live_ref.artifact_id))
            self.assertIsNone(service.read_meta(orphan_ref.artifact_id))

    async def test_purge_orphaned_removes_corrupt_meta_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = FilesystemArtifactService(Path(tmp))
            (Path(tmp) / "artifacts" / "bad-id.meta.json").write_text("not json")
            (Path(tmp) / "artifacts" / "bad-id.content").write_text("stray content")

            deleted = service.purge_orphaned(set())

            self.assertEqual(deleted, 1)
            self.assertFalse((Path(tmp) / "artifacts" / "bad-id.content").exists())


if __name__ == "__main__":
    unittest.main()
