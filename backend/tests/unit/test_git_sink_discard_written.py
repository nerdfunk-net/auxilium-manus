"""GitArtifactSink.discard_written: undo this sink's uncommitted writes, nothing else."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import git

from services.artifacts.sinks.git_sink import GitArtifactSink


class DiscardWrittenTests(unittest.TestCase):
    def _sink(self, root: Path) -> GitArtifactSink:
        with patch("service_factory.build_git_service"):
            sink = GitArtifactSink({"id": 1, "name": "r"}, repository_subdirectory="aci")
        sink._repo = git.Repo(root)  # noqa: SLF001 - a prepared sink
        return sink

    def test_a_tracked_file_goes_back_a_new_file_is_deleted_others_are_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = git.Repo.init(root)
            with repo.config_writer() as cfg:
                cfg.set_value("user", "name", "t")
                cfg.set_value("user", "email", "t@example.com")
            (root / "aci").mkdir()
            (root / "aci" / "kept.json").write_text("old\n")
            (root / "mine.txt").write_text("unrelated\n")
            repo.git.add("-A")
            repo.git.commit("-m", "init")
            (root / "mine.txt").write_text("edited by someone else\n")
            with patch("services.artifacts.sinks.git_sink.get_repo_path", return_value=root):
                sink = self._sink(root)
                for name, content in (("kept.json", "new\n"), ("fresh.json", "{}\n")):
                    asyncio.run(
                        sink.write_text(
                            relative_path=name, content=content, workflow_id="w", run_id="r"
                        )
                    )
                self.assertEqual(asyncio.run(sink.discard_written()), 2)
            self.assertEqual((root / "aci" / "kept.json").read_text(), "old\n")
            self.assertFalse((root / "aci" / "fresh.json").exists())
            self.assertEqual((root / "mine.txt").read_text(), "edited by someone else\n")
            self.assertFalse(sink.has_writes)

    def test_nothing_written_is_nothing_to_undo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git.Repo.init(root)
            with patch("services.artifacts.sinks.git_sink.get_repo_path", return_value=root):
                self.assertEqual(asyncio.run(self._sink(root).discard_written()), 0)
