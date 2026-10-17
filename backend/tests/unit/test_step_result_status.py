"""Tests for workflow step status derivation."""

from __future__ import annotations

import unittest

from models.workflow_context import StepOutcome, WorkflowContext
from services.execution.step_result_status import derive_step_result_status


class StepResultStatusTests(unittest.TestCase):
    def test_git_workflow_failure_without_devices(self) -> None:
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            metadata={
                "git-pull-1.git_operation": {
                    "success": False,
                    "message": "pull failed",
                }
            },
        )
        outcomes = [
            StepOutcome(name="success", context=context.model_copy(update={"devices": {}})),
            StepOutcome(name="failure", context=context),
        ]
        status = derive_step_result_status(outcomes=outcomes, input_context=context)
        self.assertEqual(status, "failed")


if __name__ == "__main__":
    unittest.main()
