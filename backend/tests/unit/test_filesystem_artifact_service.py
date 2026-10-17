"""Tests for filesystem artifact storage."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
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

            deleted = service.purge_orphaned({"run-live"}, now=time.time() + 7200)

            self.assertEqual(deleted, 1)
            self.assertIsNotNone(service.read_meta(live_ref.artifact_id))
            self.assertIsNone(service.read_meta(orphan_ref.artifact_id))

    async def test_purge_orphaned_removes_corrupt_meta_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = FilesystemArtifactService(Path(tmp))
            (Path(tmp) / "artifacts" / "bad-id.meta.json").write_text("not json")
            (Path(tmp) / "artifacts" / "bad-id.content").write_text("stray content")

            deleted = service.purge_orphaned(set(), now=time.time() + 7200)

            self.assertEqual(deleted, 1)
            self.assertFalse((Path(tmp) / "artifacts" / "bad-id.content").exists())

    async def test_purge_keeps_young_artifact_of_unknown_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = FilesystemArtifactService(Path(tmp))
            ref = await service.store(
                content="b", kind="running_config", device_id="d1", run_id="run-new"
            )

            deleted = service.purge_orphaned(set())

            self.assertEqual(deleted, 0)
            self.assertIsNotNone(service.read_meta(ref.artifact_id))

    async def test_purge_removes_old_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = FilesystemArtifactService(Path(tmp))
            ref = await service.store(
                content="b", kind="running_config", device_id="d1", run_id="run-gone"
            )
            old = time.time() - 7200
            for suffix in (".meta.json", ".content"):
                path = Path(tmp) / "artifacts" / f"{ref.artifact_id}{suffix}"
                if path.exists():
                    os.utime(path, (old, old))

            self.assertEqual(service.purge_orphaned(set()), 1)

    async def test_meta_is_never_observed_half_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = FilesystemArtifactService(Path(tmp))
            meta_path = Path(tmp) / "artifacts" / "x.meta.json"
            stop = threading.Event()
            seen_bad: list[str] = []

            def reader() -> None:
                while not stop.is_set():
                    try:
                        text = meta_path.read_text(encoding="utf-8")
                    except FileNotFoundError:
                        continue
                    try:
                        json.loads(text)
                    except json.JSONDecodeError:
                        seen_bad.append(text[:40])

            thread = threading.Thread(target=reader)
            thread.start()
            try:
                big = {"run_id": "r", "kind": "k", "pad": "x" * 200_000}
                for _ in range(40):
                    service._write_files("x", "content", big)
            finally:
                stop.set()
                thread.join()
            self.assertEqual(seen_bad, [])


if __name__ == "__main__":
    unittest.main()
