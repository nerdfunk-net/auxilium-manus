"""A start-workflow step must not carry a secret value for the workflow it starts.

``pluginConfig.run_inputs`` is saved in ``workflows.canvas_nodes`` as plain JSON, readable by
everyone who can read the workflow; a ``secret`` run input is only sealed when a run is created.
So the save refuses a secret input in the step (and the executor refuses it for workflows that
were imported or written before this rule).
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock

from core.domain_exceptions import ValidationFailedError
from models.workflows import WorkflowCreate, WorkflowUpdate
from services.workflow.child_run_inputs import (
    secret_inputs_given,
    validate_start_workflow_secret_inputs,
)
from services.workflow.workflow_service import WorkflowService

ATTRS = [
    {"name": "tacacs_key", "type": "secret", "default": None, "required": True},
    {"name": "site", "type": "string", "default": "lab", "required": False},
]


def _node(run_inputs, *, workflow_id=7, kind="start-workflow", node_id="n1", title="Backup"):
    return {
        "id": node_id,
        "data": {
            "kind": kind,
            "title": title,
            "pluginConfig": {"workflow_id": workflow_id, "run_inputs": run_inputs},
        },
    }


class SecretInputsGivenTests(unittest.TestCase):
    def test_names_only_the_secret_inputs_that_are_given(self) -> None:
        self.assertEqual(
            secret_inputs_given({"tacacs_key": "x", "site": "y"}, ATTRS), ["tacacs_key"]
        )
        self.assertEqual(secret_inputs_given({"site": "y"}, ATTRS), [])

    def test_tolerates_missing_schema_and_odd_inputs(self) -> None:
        self.assertEqual(secret_inputs_given({"a": 1}, None), [])
        self.assertEqual(secret_inputs_given(None, ATTRS), [])
        self.assertEqual(secret_inputs_given({"a": 1}, ["junk", {"no": "name"}]), [])


class ValidateOnSaveTests(unittest.TestCase):
    def test_a_secret_input_in_a_step_is_refused_with_a_message_naming_everything(self) -> None:
        with self.assertRaises(ValidationFailedError) as ctx:
            validate_start_workflow_secret_inputs(
                [_node({"tacacs_key": "hunter2"})], lambda wid: ATTRS
            )
        message = str(ctx.exception)
        for part in ("Backup", "tacacs_key", "secret"):
            self.assertIn(part, message)
        self.assertNotIn("hunter2", message)

    def test_non_secret_inputs_and_other_steps_pass(self) -> None:
        validate_start_workflow_secret_inputs(
            [_node({"site": "x"}), _node({"tacacs_key": "x"}, kind="run-command")],
            lambda wid: ATTRS,
        )

    def test_an_unknown_target_is_not_this_validators_business(self) -> None:
        validate_start_workflow_secret_inputs([_node({"tacacs_key": "x"})], lambda wid: None)

    def test_a_node_without_inputs_or_workflow_id_is_skipped(self) -> None:
        looked_up: list[int] = []

        def lookup(wid: int):
            looked_up.append(wid)
            return ATTRS

        validate_start_workflow_secret_inputs(
            [_node({}), _node({"tacacs_key": "x"}, workflow_id=None)], lookup
        )
        self.assertEqual(looked_up, [])


class WorkflowServiceSaveTests(unittest.TestCase):
    """The rule is enforced where the definition is saved, before anything is written."""

    def _service(self) -> WorkflowService:
        service = WorkflowService(MagicMock())
        target = SimpleNamespace(
            id=7, name="backup", static_attributes=ATTRS, creator_id=1, visibility="public"
        )
        self.target = target
        existing = SimpleNamespace(
            id=3, creator_id=1, visibility="private", canvas_nodes=[], canvas_edges=[]
        )
        service.repo = MagicMock()
        service.repo.name_exists.return_value = False
        service.repo.get_by_id.side_effect = lambda wid: (
            (target, "u") if wid == 7 else (existing, "u")
        )
        return service

    def test_create_refuses_a_secret_input_in_the_step(self) -> None:
        service = self._service()
        data = WorkflowCreate(name="change", canvas_nodes=[_node({"tacacs_key": "hunter2"})])
        with self.assertRaises(ValidationFailedError) as ctx:
            service.create_workflow(data, user_id=1)
        self.assertNotIn("hunter2", str(ctx.exception))
        service.repo.create.assert_not_called()

    def test_a_private_workflow_of_someone_else_is_neither_inspected_nor_revealed(self) -> None:
        """The save must not confirm that a private workflow exists, nor name it or its inputs."""
        service = self._service()
        self.target.visibility = "private"
        self.target.creator_id = 2
        service._validate_child_run_secret_inputs([_node({"tacacs_key": "x"})], user_id=1)

    def test_the_owner_of_a_private_workflow_is_still_checked(self) -> None:
        service = self._service()
        self.target.visibility = "private"
        with self.assertRaises(ValidationFailedError):
            service._validate_child_run_secret_inputs([_node({"tacacs_key": "x"})], user_id=1)

    def test_update_refuses_a_secret_input_in_the_step(self) -> None:
        service = self._service()
        data = WorkflowUpdate(canvas_nodes=[_node({"tacacs_key": "hunter2"})])
        with self.assertRaises(ValidationFailedError):
            service.update_workflow(3, data, user_id=1)
        service.repo.update.assert_not_called()


if __name__ == "__main__":
    unittest.main()
