"""Tests for artifact storage."""

from __future__ import annotations

import unittest

from services.artifacts import InMemoryArtifactService


class InMemoryArtifactServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_store_and_resolve_round_trip(self) -> None:
        service = InMemoryArtifactService()
        ref = await service.store(
            content="hostname router1",
            kind="running_config",
            device_id="device-1",
            run_id="run-1",
        )
        content = await service.resolve(ref)
        self.assertEqual(content, "hostname router1")
        self.assertEqual(ref.kind, "running_config")
        self.assertIsNotNone(ref.sha256)


if __name__ == "__main__":
    unittest.main()
