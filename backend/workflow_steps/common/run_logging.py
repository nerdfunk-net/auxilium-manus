"""The run identifier a step writes into its log lines (W11-10).

``WorkflowRun.id`` is the database integer; ``WorkflowRun.uuid`` is what ``context.run_id``
carries and what an operator sees in the UI, the API and the other log lines. A step logs the
UUID, always through this helper, so one ``run_id=`` value greps across the whole run.
"""

from __future__ import annotations

from core.models.runs import WorkflowRun


def log_run_id(run: WorkflowRun) -> str:
    """The run's UUID as the string ``context.run_id`` holds."""
    return str(run.uuid)
