"""Tests for step-failure error classification and surfacing (M6).

Steps raise ValueError for configuration problems and RuntimeError for
execution failures with human-readable messages (doc/WORKFLOW-STEPS.md);
those messages are safe to persist and show to end users. Any other
exception type is unanticipated and may contain internals, so only a
generic message plus a correlatable error_id is persisted.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

from models.workflow_context import WorkflowContext
from services.execution.step_runner import StepRunner, classify_step_exception


class ClassifyStepExceptionTests(unittest.TestCase):
    def test_value_error_is_configuration_category_with_original_message(self) -> None:
        category, message = classify_step_exception(
            ValueError("get-nautobot-devices: nautobot_source_id is not configured")
        )
        self.assertEqual(category, "configuration")
        self.assertEqual(message, "get-nautobot-devices: nautobot_source_id is not configured")

    def test_runtime_error_is_execution_category_with_original_message(self) -> None:
        category, message = classify_step_exception(RuntimeError("device unreachable: 10.0.0.1"))
        self.assertEqual(category, "execution")
        self.assertEqual(message, "device unreachable: 10.0.0.1")

    def test_unexpected_exception_is_internal_category_with_generic_message(self) -> None:
        category, message = classify_step_exception(KeyError("secret_internal_key"))
        self.assertEqual(category, "internal")
        self.assertNotIn("secret_internal_key", message)

    def test_empty_message_falls_back_to_a_generic_but_categorized_message(self) -> None:
        category, message = classify_step_exception(ValueError())
        self.assertEqual(category, "configuration")
        self.assertTrue(message)


class StepRunnerErrorPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def _run_with_exception(self, exc: Exception) -> dict[str, Any]:
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
            raise exc

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
        self.assertEqual(captured.get("status"), "failed")
        return captured

    async def test_value_error_message_is_persisted_verbatim_with_category(self) -> None:
        captured = await self._run_with_exception(
            ValueError("get-nautobot-devices: nautobot_source_id is not configured")
        )
        self.assertEqual(
            captured.get("error_message"),
            "get-nautobot-devices: nautobot_source_id is not configured",
        )
        self.assertEqual(captured.get("error_category"), "configuration")
        self.assertTrue(captured.get("error_id"))

    async def test_unexpected_exception_omits_exception_text_but_keeps_error_id(self) -> None:
        captured = await self._run_with_exception(RuntimeError("secret path /var/app"))
        # RuntimeError is a step-authored "execution failure" per doc/WORKFLOW-STEPS.md,
        # so its message is shown as-is here — this is the intentional M6 behaviour
        # change from the earlier blanket-sanitized message.
        self.assertEqual(captured.get("error_message"), "secret path /var/app")
        self.assertEqual(captured.get("error_category"), "execution")

        captured_internal = await self._run_with_exception(TypeError("internal detail: /var/app"))
        self.assertNotIn("/var/app", captured_internal.get("error_message", ""))
        self.assertEqual(captured_internal.get("error_category"), "internal")
        self.assertTrue(captured_internal.get("error_id"))


if __name__ == "__main__":
    unittest.main()
