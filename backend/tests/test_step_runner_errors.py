"""Tests for sanitized step-failure error messages (M5)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from models.workflow_context import WorkflowContext
from services.execution.step_runner import StepRunner


class StepRunnerErrorSanitizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_persisted_error_message_omits_traceback_and_exception_text(self) -> None:
        runner = StepRunner.__new__(StepRunner)
        runner.repo = MagicMock()
        runner.artifact_service = MagicMock()
        runner.plugin_registry = MagicMock()

        step_result = SimpleNamespace(status="running", error_message=None)
        captured: dict[str, Any] = {}

        def _update_step_result(result, **kwargs):
            captured.update(kwargs)
            for key, value in kwargs.items():
                setattr(result, key, value)
            return result

        runner.repo.update_step_result.side_effect = _update_step_result

        async def _boom(**_kwargs):
            raise RuntimeError("secret path /var/app")

        with (
            patch.object(
                runner,
                "_assemble_input_context",
                return_value=WorkflowContext(run_id="run-1", workflow_id="wf-1"),
            ),
            patch.object(runner, "_execute_step", side_effect=_boom),
        ):
            ok = await runner._execute_and_persist_node(
                node={"id": "n1", "data": {"kind": "log-message", "pluginConfig": {}}},
                run=SimpleNamespace(id=1, uuid="run-uuid"),
                workflow=SimpleNamespace(id=1),
                edges=[],
                step_outcomes={},
                step_result=step_result,
            )

        self.assertFalse(ok)
        message = captured.get("error_message", "")
        self.assertIn("error_id=", message)
        self.assertIn("RuntimeError", message)
        self.assertNotIn("/var/app", message)
        self.assertNotIn("Traceback", message)
        self.assertEqual(captured.get("status"), "failed")


if __name__ == "__main__":
    unittest.main()
