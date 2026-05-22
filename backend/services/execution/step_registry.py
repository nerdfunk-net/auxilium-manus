"""Registry mapping step type identifiers to async executor functions.

Each executor lives in workflow_steps/{step_dir}/executor.py and must expose:

    async def execute(*, config, parent_outputs, run) -> dict[str, Any]: ...

To add a new step type:
  1. Create workflow_steps/{step_dir}/executor.py with an `execute` function.
  2. Import it below and add an entry to STEP_REGISTRY.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from workflow_steps.get_nautobot_devices.executor import execute as get_nautobot_devices
from workflow_steps.nautobot_attributes.executor import execute as get_nautobot_attributes

StepExecutor = Callable[..., Awaitable[dict[str, Any]]]

STEP_REGISTRY: dict[str, StepExecutor] = {
    "get-nautobot-devices": get_nautobot_devices,
    "get-nautobot-attributes": get_nautobot_attributes,
}
