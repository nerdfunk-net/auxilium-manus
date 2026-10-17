"""Tests that canvas decorations are excluded from the execution plan."""

from __future__ import annotations

import unittest
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.models.runs import WorkflowRun, WorkflowStepResult
from core.models.users import User
from services.execution.step_runner import StepRunner


def _node(node_id: str, kind: str) -> dict[str, Any]:
    return {"id": node_id, "data": {"kind": kind, "title": kind}}


def _edge(source: str, target: str) -> dict[str, Any]:
    return {"source": source, "target": target}


def _make_session() -> tuple[Session, Any]:
    engine = create_engine("sqlite:///:memory:")
    WorkflowRun.metadata.create_all(
        engine,
        tables=[User.__table__, WorkflowRun.__table__, WorkflowStepResult.__table__],
    )
    return sessionmaker(bind=engine)(), engine


class CanvasDecorationExecutionPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db, engine = _make_session()
        self.addCleanup(engine.dispose)
        self.addCleanup(self.db.close)
        self.runner = StepRunner(self.db)

    def test_label_and_background_excluded_from_execution_plan(self) -> None:
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("cmd", "run-command"),
            _node("lbl", "label"),
            _node("bg", "background"),
        ]
        edges = [_edge("inv", "cmd")]

        plan = self.runner.build_execution_plan(nodes, edges)
        plan_ids = [n["id"] for n in plan]

        self.assertEqual(plan_ids, ["inv", "cmd"])
        self.assertNotIn("lbl", plan_ids)
        self.assertNotIn("bg", plan_ids)

    def test_decoration_edges_are_ignored(self) -> None:
        """If a stray edge touches a decoration, it must not affect the plan."""
        nodes = [
            _node("a", "get-nautobot-devices"),
            _node("b", "run-command"),
            _node("lbl", "label"),
        ]
        edges = [
            _edge("a", "b"),
            _edge("a", "lbl"),
            _edge("lbl", "b"),
        ]

        plan = self.runner.build_execution_plan(nodes, edges)
        self.assertEqual([n["id"] for n in plan], ["a", "b"])

    def test_pending_step_results_skip_decorations(self) -> None:
        nodes = [
            _node("inv", "get-nautobot-devices"),
            _node("lbl", "label"),
            _node("bg", "background"),
        ]
        plan = self.runner.build_execution_plan(nodes, [])

        # Avoid hitting the real DB create path — just assert plan content.
        self.assertEqual([n["id"] for n in plan], ["inv"])
        self.assertTrue(all(self.runner._is_executable_node(n) for n in plan))

    def test_is_executable_unknown_kind_stays_true(self) -> None:
        self.assertTrue(self.runner._is_executable_node(_node("x", "not-a-real-step")))

    def test_is_executable_label_is_false(self) -> None:
        self.assertFalse(self.runner._is_executable_node(_node("lbl", "label")))
        self.assertFalse(self.runner._is_executable_node(_node("bg", "background")))


if __name__ == "__main__":
    unittest.main()
