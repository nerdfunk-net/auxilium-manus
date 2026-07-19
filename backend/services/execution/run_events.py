"""Hatchet event-key formats shared between the worker (waiting) and the API
(pushing) sides of a run's user-driven pauses — debug-mode "Next Step" and
Wait & Run batch approval.

A "Next Step"/"Run to completion"/"Run next batch" click can race the durable
wait's own registration with the Hatchet engine: the run is marked "paused" in
the DB (which is what makes the frontend button clickable) slightly before
``ctx.aio_wait_for_event`` actually finishes subscribing. Without ``scope`` +
``lookback_window``, an event pushed in that gap is silently dropped (the SDK
only matches events arriving after registration), requiring a second click.
Scoping to the event key itself and looking back generously covers it.
"""

from __future__ import annotations

from datetime import timedelta

STEP_EVENT_LOOKBACK = timedelta(minutes=15)


def debug_step_event_key(run_uuid: str, node_id: str) -> str:
    return f"workflow-run.{run_uuid}.step.{node_id}"


def batch_approval_event_key(run_uuid: str, batch_index: int) -> str:
    return f"workflow-run.{run_uuid}.batch.{batch_index}"
