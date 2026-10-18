"""Run inputs a start-workflow step passes to the workflow it starts.

``pluginConfig.run_inputs`` is saved in ``workflows.canvas_nodes`` as plain JSON, visible to
everyone who can read the workflow. A ``secret`` run input is only sealed when a run is created, so
a secret value typed into a step would sit in the definition in cleartext. A secret therefore can
never be given by the step; this module names the offending inputs for the save-time check
(``WorkflowService``) and the run-time check (the step executor).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from core.domain_exceptions import ValidationFailedError

START_WORKFLOW_KIND = "start-workflow"

StaticAttributeLookup = Callable[[int], list[dict[str, Any]] | None]


def _workflow_id(value: Any) -> int | None:
    try:
        return int(value)
    except TypeError, ValueError:
        return None


def secret_inputs_given(run_inputs: Any, static_attributes: Any) -> list[str]:
    """Names of declared ``secret`` inputs that ``run_inputs`` supplies a value for."""
    if not isinstance(run_inputs, dict) or not isinstance(static_attributes, list):
        return []
    secret_names = {
        attr["name"]
        for attr in static_attributes
        if isinstance(attr, dict)
        and attr.get("type") == "secret"
        and isinstance(attr.get("name"), str)
    }
    return sorted(name for name in run_inputs if name in secret_names)


def secret_input_message(step_name: str, target_name: str, names: Iterable[str]) -> str:
    """Never contains a value, only names."""
    listed = ", ".join(repr(name) for name in names)
    return (
        f"Run Workflow step {step_name!r}: input(s) {listed} of workflow {target_name!r} are "
        "secrets and cannot be set in a step, because the value would be stored in the workflow "
        "definition in cleartext. A workflow that needs a secret run input cannot be started by "
        "this step."
    )


def validate_start_workflow_secret_inputs(
    canvas_nodes: list[dict[str, Any]],
    lookup: StaticAttributeLookup,
    *,
    target_names: Callable[[int], str] | None = None,
) -> None:
    """Raise HTTP 400 when a start-workflow node gives a value for a secret input of its target.

    ``lookup`` returns the target's declared inputs, or None for an unknown workflow (reported at
    run time, not here).
    """
    for node in canvas_nodes:
        data = node.get("data") if isinstance(node, dict) else None
        if not isinstance(data, dict) or data.get("kind") != START_WORKFLOW_KIND:
            continue
        config = data.get("pluginConfig")
        if not isinstance(config, dict) or not config.get("run_inputs"):
            continue
        workflow_id = _workflow_id(config.get("workflow_id"))
        if workflow_id is None:
            continue
        offending = secret_inputs_given(config.get("run_inputs"), lookup(workflow_id))
        if offending:
            target = (
                target_names(workflow_id)
                if target_names
                else str(config.get("workflow_name") or workflow_id)
            )
            step_name = str(data.get("title") or node.get("id") or START_WORKFLOW_KIND)
            raise ValidationFailedError(secret_input_message(step_name, target, offending))
