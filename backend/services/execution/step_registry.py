"""Registry mapping step type identifiers to async executor functions.

Each executor receives:
  config        — node data dict from the canvas (step configuration)
  parent_outputs — dict of {node_id: output_dict} for upstream steps
  run           — the WorkflowRun ORM instance

It returns a JSON-serialisable dict that becomes the step's output.

To add a new step type:
  1. Implement an async executor function below.
  2. Register it in STEP_REGISTRY under the step's type string.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from core.models.runs import WorkflowRun

StepExecutor = Callable[..., Awaitable[dict[str, Any]]]


async def _execute_get_nautobot_devices(
    *,
    config: dict[str, Any],
    parent_outputs: dict[str, Any],
    run: WorkflowRun,
) -> dict[str, Any]:
    return {
        "devices": run.device_ids or [],
        "source_id": config.get("nautobot_source_id", ""),
    }


async def _execute_get_nautobot_attributes(
    *,
    config: dict[str, Any],
    parent_outputs: dict[str, Any],
    run: WorkflowRun,
) -> dict[str, Any]:
    # Collect device list from the closest parent that produced devices
    devices: list[str] = []
    for output in parent_outputs.values():
        if isinstance(output, dict) and "devices" in output:
            devices = output["devices"]
            break

    return {
        "devices": devices,
        "attributes": config.get("attributes", []),
    }


STEP_REGISTRY: dict[str, StepExecutor] = {
    "get_nautobot_devices": _execute_get_nautobot_devices,
    "get_nautobot_attributes": _execute_get_nautobot_attributes,
}
