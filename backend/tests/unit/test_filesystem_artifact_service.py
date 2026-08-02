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


if __name__ == "__main__":
    unittest.main()
