"""Registry mapping step type identifiers to async executor functions.

Each executor lives in workflow_steps/{step_dir}/executor.py and must expose:

    async def execute(
        *, config, context, run, artifact_service, node_id
    ) -> list[StepOutcome]: ...

To add a new step type:
  1. Create workflow_steps/{step_dir}/executor.py with an `execute` function.
  2. Import it below and add an entry to STEP_REGISTRY.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from models.workflow_context import StepOutcome
from workflow_steps.get_git_devices.executor import execute as get_git_devices
from workflow_steps.get_nautobot_devices.executor import execute as get_nautobot_devices
from workflow_steps.nautobot_attributes.executor import execute as get_nautobot_attributes

StepExecutor = Callable[..., Awaitable[list[StepOutcome]]]

STEP_REGISTRY: dict[str, StepExecutor] = {
    "get-nautobot-devices": get_nautobot_devices,
    "get-git-devices": get_git_devices,
    "get-nautobot-attributes": get_nautobot_attributes,
}
