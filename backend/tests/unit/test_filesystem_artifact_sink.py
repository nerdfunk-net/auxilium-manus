"""Tests for FilesystemArtifactSink path sanitization (M2)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from services.artifacts.sinks.filesystem_sink import FilesystemArtifactSink


class FilesystemArtifactSinkTests(unittest.IsolatedAsyncioTestCase):
    def test_default_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sink = FilesystemArtifactSink(Path(tmp))
            self.assertEqual(sink._output_subdirectory, "exports")

    def test_accepts_nested_subdirectory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sink = FilesystemArtifactSink(Path(tmp), output_subdirectory="team/exports")
            self.assertEqual(sink._output_subdirectory, "team/exports")

    def test_rejects_parent_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ("../outside", "foo/../../etc", "/abs"):
                with self.subTest(subdir=bad):
                    with self.assertRaises(ValueError):
                        FilesystemArtifactSink(Path(tmp), output_subdirectory=bad)

    async def test_write_text_still_rejects_relative_path_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sink = FilesystemArtifactSink(Path(tmp), output_subdirectory="exports")
            with self.assertRaises(ValueError):
                await sink.write_text(
                    relative_path="../x",
                    content="data",
                    workflow_id="wf-1",
                    run_id="run-1",
                )


if __name__ == "__main__":
    unittest.main()
