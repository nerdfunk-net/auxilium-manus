"""Step-runner package: executes all steps of a workflow run in topological
order.

Split into modules (2026-09):
  runner.py            the StepRunner class + _plugin_registry_service
  graph_resolution.py  pure canvas-graph resolution (funnels, disabled steps,
                       executable filtering, topological order)
  signals.py           FanOutSignal + classify_step_exception

Everything other modules and tests import from ``services.execution.step_runner``
is re-exported here, so no import path changes.
"""

from __future__ import annotations

from services.execution.step_runner.runner import (
    StepRunner,
    # Re-exported ONLY so existing patch("services.execution.step_runner.<x>")
    # targets keep importing. The class in runner.py calls the name bound in
    # runner.py, so string patch targets must point at
    # ``services.execution.step_runner.runner.<x>`` (see
    # test_step_runner_device_sessions.py).
    capability_spec_from_plugin,
    effective_produces,
    post_step_guard,
    pre_step_guard,
)
from services.execution.step_runner.signals import FanOutSignal, classify_step_exception

__all__ = [
    "FanOutSignal",
    "StepRunner",
    "capability_spec_from_plugin",
    "classify_step_exception",
    "effective_produces",
    "post_step_guard",
    "pre_step_guard",
]
