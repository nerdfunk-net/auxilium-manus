"""Tests for step result status derivation."""

from __future__ import annotations

import unittest

from models.workflow_context import DeviceContext, DeviceStatus, StepOutcome, WorkflowContext
from services.execution.step_result_status import derive_step_result_status


def _context(*device_ids: str) -> WorkflowContext:
    return WorkflowContext(
        run_id="run-1",
        workflow_id="1",
        devices={
            device_id: DeviceContext(
                id=device_id,
                name=device_id,
                hostname=device_id,
                status=DeviceStatus.OK,
            )
            for device_id in device_ids
        },
    )


class StepResultStatusTests(unittest.TestCase):
    def test_all_success(self) -> None:
        input_ctx = _context()
        outcomes = [
            StepOutcome(name="success", context=_context("d1")),
        ]
        self.assertEqual(
            derive_step_result_status(outcomes=outcomes, input_context=input_ctx),
            "success",
        )

    def test_all_failed_on_failure_outcome(self) -> None:
        input_ctx = _context("d1")
        outcomes = [
            StepOutcome(name="success", context=_context()),
            StepOutcome(name="failure", context=_context("d1")),
        ]
        self.assertEqual(
            derive_step_result_status(outcomes=outcomes, input_context=input_ctx),
            "failed",
        )

    def test_partial_success_and_failure(self) -> None:
        input_ctx = _context("d1", "d2")
        outcomes = [
            StepOutcome(name="success", context=_context("d1")),
            StepOutcome(name="failure", context=_context("d2")),
        ]
        self.assertEqual(
            derive_step_result_status(outcomes=outcomes, input_context=input_ctx),
            "partial",
        )


if __name__ == "__main__":
    unittest.main()
