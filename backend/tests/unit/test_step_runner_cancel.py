"""C1-03: a fan-out child stops between waves once the parent run is cancelled."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from models.workflow_context import WorkflowContext
from services.execution.step_runner import subgraph


def _node(node_id: str) -> dict[str, Any]:
    return {"id": node_id, "data": {"kind": "x", "title": node_id}}


class SubgraphCancelTests(unittest.IsolatedAsyncioTestCase):
    async def _walk(self, *, cancel_after: str | None):
        nodes = [_node("inv"), _node("a"), _node("b"), _node("c")]
        edges = [
            {"source": "inv", "target": "a"},
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
        ]
        state = SimpleNamespace(cancelled=False)
        executed: list[str] = []

        async def run_one(runner: Any, *, node: dict[str, Any], **_kw: Any) -> None:
            executed.append(node["id"])
            if node["id"] == cancel_after:
                state.cancelled = True

        runner = MagicMock()
        runner.load_execution_graph.return_value = (nodes, edges)
        runner._topological_sort.return_value = nodes
        runner._cancel_requested = AsyncMock(side_effect=lambda _run: state.cancelled)
        progress = MagicMock()
        initial = WorkflowContext(run_id="r", workflow_id="1", devices={})

        with (
            patch.object(subgraph, "_run_one_subgraph_node", run_one),
            patch.object(subgraph, "report_node_finished", AsyncMock()) as reported,
        ):
            await subgraph.run_subgraph(
                runner,
                run=MagicMock(),
                workflow=MagicMock(),
                initial_context=initial,
                inventory_node_id="inv",
                allowed_node_ids={"a", "b", "c"},
                progress=progress,
            )
        return executed, reported

    async def test_child_keeps_walking_when_nobody_cancelled(self) -> None:
        executed, _ = await self._walk(cancel_after=None)
        self.assertEqual(executed, ["a", "b", "c"])

    async def test_child_stops_at_the_next_wave_after_cancel(self) -> None:
        executed, reported = await self._walk(cancel_after="a")
        self.assertEqual(executed, ["a"])
        skipped = [call.args[1] for call in reported.await_args_list if call.args[2] == "skipped"]
        self.assertEqual(skipped, ["b", "c"])


if __name__ == "__main__":
    unittest.main()
