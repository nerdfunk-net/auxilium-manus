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
from workflow_steps.compare_data.executor import execute as compare_data
from workflow_steps.fan_in.executor import execute as fan_in
from workflow_steps.filter_output.executor import execute as filter_output
from workflow_steps.get_device_configs.executor import execute as get_device_configs
from workflow_steps.get_from_list.executor import execute as get_from_list
from workflow_steps.get_git_devices.executor import execute as get_git_devices
from workflow_steps.get_ise_devices.executor import execute as get_ise_devices
from workflow_steps.get_nautobot_devices.executor import execute as get_nautobot_devices
from workflow_steps.git_clone.executor import execute as git_clone
from workflow_steps.git_pull.executor import execute as git_pull
from workflow_steps.git_push.executor import execute as git_push
from workflow_steps.merge_content.executor import execute as merge_content
from workflow_steps.get_nautobot_attributes.executor import execute as get_nautobot_attributes
from workflow_steps.render_jinja_template.executor import execute as render_jinja_template
from workflow_steps.route_on_attribute.executor import execute as route_on_attribute
from workflow_steps.run_command.executor import execute as run_command
from workflow_steps.store_artifact.executor import execute as store_artifact
from workflow_steps.update_attribute.executor import execute as update_attribute
from workflow_steps.update_nautobot_device.executor import execute as update_nautobot_device
from workflow_steps.show_attributes.executor import execute as show_attributes
from workflow_steps.workflow_log.executor import execute as workflow_log

StepExecutor = Callable[..., Awaitable[list[StepOutcome]]]

STEP_REGISTRY: dict[str, StepExecutor] = {
    "get-nautobot-devices": get_nautobot_devices,
    "get-from-list": get_from_list,
    "get-git-devices": get_git_devices,
    "get-ise-devices": get_ise_devices,
    "get-nautobot-attributes": get_nautobot_attributes,
    "get-device-configs": get_device_configs,
    "render-jinja-template": render_jinja_template,
    "run-command": run_command,
    "route-on-attribute": route_on_attribute,
    "fan-in": fan_in,
    "merge-content": merge_content,
    "filter-output": filter_output,
    "compare-data": compare_data,
    "store-artifact": store_artifact,
    "git-clone": git_clone,
    "git-pull": git_pull,
    "git-push": git_push,
    "update-attribute": update_attribute,
    "update-nautobot-device": update_nautobot_device,
    "workflow-log": workflow_log,
    "show-attributes": show_attributes,
}
