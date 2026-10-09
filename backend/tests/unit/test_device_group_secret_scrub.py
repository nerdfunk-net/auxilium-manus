"""A fan-out child scrubs every secret it decrypted from the result it hands to the parent (W6)."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from hatchet.workflows import device_group_execution as mod
from models.workflow_context import DeviceContext, StepOutcome, WorkflowContext
from services.workflow_context.secret_fields import (
    REDACTED_PLACEHOLDER,
    register_secret_value,
    seal_secret,
)

_SECRET = "tacacs-key-12345"


def _context(text: str, **extra) -> WorkflowContext:
    device = DeviceContext(
        id="d1", name="d1", hostname="d1", errors=[], parsed={"run": {"output": text}}, **extra
    )
    return WorkflowContext(run_id="r", workflow_id="1", devices={"d1": device})


class DeviceGroupSecretScrubTests(unittest.IsolatedAsyncioTestCase):
    async def test_child_result_and_errors_are_scrubbed_before_returning(self) -> None:
        sealed = seal_secret(_SECRET)
        leaked = _context(f"login with {_SECRET} ok")
        leaked.devices["d1"].attribute_bags["tacacs"] = {"shared_secret": sealed}

        async def fake_execute_subgraph(**_kwargs):
            register_secret_value(_SECRET)  # what unwrap_secret / get_decrypted_* do
            outcomes = {
                "inventory": {"success": StepOutcome(name="success", context=leaked).context},
                "cmd": {"success": leaked},
            }
            errors = {"cmd": {"message": f"boom {_SECRET}", "category": "x", "error_id": "e"}}
            return outcomes, errors

        runner = MagicMock()
        runner.execute_subgraph = fake_execute_subgraph
        runner.close_device_sessions = AsyncMock()
        run = MagicMock(workflow_id=1)
        db = MagicMock()
        session_cm = MagicMock()
        session_cm.__enter__.return_value = db
        run_repo = MagicMock()
        run_repo.get_run_by_id.return_value = (run, None)
        wf = MagicMock(canvas_nodes=[], canvas_edges=[])
        wf_repo = MagicMock()
        wf_repo.get_by_id.return_value = (wf, None)

        with (
            patch("core.database.SessionLocal", return_value=session_cm),
            patch("repositories.run_repository.RunRepository", return_value=run_repo),
            patch("repositories.workflow_repository.WorkflowRepository", return_value=wf_repo),
            patch("services.execution.step_runner.StepRunner", return_value=runner),
            patch("services.execution.graph.child_node_ids", return_value={"cmd"}),
            patch("services.execution.step_runner.progress.DeviceGroupProgressSink"),
            patch.object(mod, "_report_group"),
        ):
            result = await mod._run_device_group(
                mod.DeviceGroupInput(
                    parent_run_id=1,
                    context_json=_context("x").model_dump_json(),
                    start_node_id="inventory",
                    child_index=0,
                )
            )

        dumped = str(result)
        self.assertNotIn(_SECRET, dumped)
        out = result["cmd"]["success"]["devices"]["d1"]["parsed"]["run"]["output"]
        self.assertEqual(out, f"login with {REDACTED_PLACEHOLDER} ok")
        self.assertEqual(
            result["__step_errors__"]["cmd"]["message"], f"boom {REDACTED_PLACEHOLDER}"
        )
        # structure the parent merges stays intact (sealed envelope is not replaced)
        bag = result["cmd"]["success"]["devices"]["d1"]["attribute_bags"]["tacacs"]
        self.assertEqual(bag["shared_secret"], sealed)

    def test_the_child_entry_point_runs_inside_a_secret_scope(self) -> None:
        self.assertTrue(hasattr(mod._run_device_group, "__wrapped__"))
