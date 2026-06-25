"""Tests for git-push helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from models.workflow_context import WorkflowContext
from workflow_steps.common.git_push_helpers import collect_export_paths_for_commit


class GitPushHelpersTests(unittest.TestCase):
    def test_collect_export_paths_from_store_artifact_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo_root = Path(tmp)
            export_file = repo_root / "configs" / "lab.cfg"
            export_file.parent.mkdir(parents=True)
            export_file.write_text("hostname lab", encoding="utf-8")

            context = WorkflowContext(
                run_id="run-1",
                workflow_id="wf-1",
                metadata={
                    "store-artifact-4.stored_artifacts": [
                        {
                            "path": str(export_file),
                            "destination": "git",
                        }
                    ]
                },
            )

            paths = collect_export_paths_for_commit(context, repo_root=repo_root)
            self.assertEqual(paths, ["configs/lab.cfg"])


if __name__ == "__main__":
    unittest.main()
