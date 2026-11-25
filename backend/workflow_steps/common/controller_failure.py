"""The whole step failed because its controller could not be read: one ``failure`` outcome.

The controller steps that add devices or write one result (the two inventory steps,
``backup-aci-config``, ``compare-aci-subnets``) have no device to mark failed, so a controller
error ends the step on the ``failure`` handle with the context unchanged and the cause as a
``FailureInfo``. The error text of the controller is not carried: the record and the fixed
summary say what failed.
"""

from __future__ import annotations

import logging

from models.failure import FailureInfo, failure_from_exception
from models.workflow_context import StepOutcome, WorkflowContext

# A controller error that carries no classification of its own.
_UNCLASSIFIED = FailureInfo(phase="api", kind="unknown", hint="check_controller")


def controller_failure_outcomes(
    context: WorkflowContext,
    exc: BaseException,
    *,
    label: str,
    step_id: str,
    logger: logging.Logger,
) -> list[StepOutcome]:
    """``[failure]``: the step's own context, ``"<label> request failed"`` and the cause."""
    logger.warning(
        "%s: %s request failed (%s) run_id=%s", step_id, label, type(exc).__name__, context.run_id
    )
    return [
        StepOutcome(
            name="failure",
            context=context,
            summary=f"{label} request failed",
            failure=failure_from_exception(exc) or _UNCLASSIFIED,
        )
    ]
