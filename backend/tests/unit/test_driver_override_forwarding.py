"""``network_driver_override`` reaches the Netmiko call of every step that dials a device (W3a-17).

The device says ``cisco_ios``; the override says ``cisco_nxos``; the connection must use the
override. Without an override the device's own driver is used.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.workflow_context import WorkflowContext
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import CommandResult as NetmikoCommandResult
from services.network.netmiko.connection import DeployResult, FileTransferResult
from tests.unit import test_deploy_rendered_template_executor as deploy_tests
from tests.unit import test_upload_config_executor as upload_tests
from tests.unit._step_helpers import make_run
from tests.unit.test_collect_client_data_executor import _device as collect_device
from tests.unit.test_run_command_executor import _device as command_device
from workflow_steps.collect_client_data.config import get_config as collect_config
from workflow_steps.collect_client_data.executor import _target
from workflow_steps.collect_client_data.options import parse_options as collect_options
from workflow_steps.deploy_rendered_template.executor import execute as deploy_execute
from workflow_steps.discover_network.config import get_config as discover_config
from workflow_steps.discover_network.executor import _seed_target
from workflow_steps.discover_network.options import parse_options as discover_options
from workflow_steps.run_command.executor import execute as command_execute
from workflow_steps.upload_config.executor import execute as upload_execute

CASES = [("cisco_nxos", "cisco_nxos"), (None, "cisco_ios"), ("  ", "cisco_ios")]


async def _call(execute, module: str, config: dict, devices: dict, artifacts=None, **patches):
    artifacts = artifacts or InMemoryArtifactService()
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=MagicMock()),
        patch(f"{module}.resolve_ssh_credential", return_value=("admin", "secret")),
        patch(f"{module}.NetmikoService") as netmiko_cls,
        patch.object(artifacts, "resolve", new=AsyncMock(return_value="interface Gi0/0\n")),
    ):
        netmiko = netmiko_cls.return_value
        for name, result in patches.items():
            setattr(netmiko, name, AsyncMock(return_value=result))
        await execute(
            config=config,
            context=WorkflowContext(run_id="r", workflow_id="w", devices=devices),
            run=make_run(),
            artifact_service=artifacts,
            node_id="n-1",
            device_sessions=MagicMock(),
        )
    return netmiko


@pytest.mark.asyncio
@pytest.mark.parametrize(("override", "expected"), CASES)
async def test_run_command_exec_mode(override, expected) -> None:
    config = {"credential_reference": "c", "commands": ["show version"], "parser": "none"}
    netmiko = await _call(
        command_execute,
        "workflow_steps.run_command.executor",
        {**config, "network_driver_override": override},
        {"d": command_device()},
        send_commands=NetmikoCommandResult(success=True, output="x", command_outputs={}),
    )
    assert netmiko.send_commands.call_args.kwargs["device_type"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(("override", "expected"), CASES)
async def test_run_command_config_mode(override, expected) -> None:
    config = {
        "credential_reference": "c",
        "commands": ["no shutdown"],
        "execution_mode": "config_mode",
        "network_driver_override": override,
    }
    netmiko = await _call(
        command_execute,
        "workflow_steps.run_command.executor",
        config,
        {"d": command_device()},
        deploy_config=DeployResult(success=True, config_output="ok"),
    )
    assert netmiko.deploy_config.call_args.kwargs["device_type"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(("override", "expected"), CASES)
async def test_deploy_rendered_template(override, expected) -> None:
    netmiko = await _call(
        deploy_execute,
        "workflow_steps.deploy_rendered_template.executor",
        deploy_tests._base_config(network_driver_override=override),
        {"d": deploy_tests._device_with_rendered_template("d")},
        deploy_config=DeployResult(success=True, config_output="ok"),
    )
    assert netmiko.deploy_config.call_args.kwargs["device_type"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(("override", "expected"), CASES)
async def test_upload_config(override, expected) -> None:
    netmiko = await _call(
        upload_execute,
        "workflow_steps.upload_config.executor",
        upload_tests._base_config(network_driver_override=override),
        {"d": upload_tests._device_with_updated_content("d")},
        upload_file=FileTransferResult(success=True, file_transferred=True, file_verified=True),
    )
    assert netmiko.upload_file.call_args.kwargs["device_type"] == expected


@pytest.mark.parametrize(("override", "expected"), CASES)
def test_collect_client_data_target(override, expected) -> None:
    options = collect_options({**collect_config(), "network_driver_override": override})
    target = _target(collect_device("d", "core1", "10.0.0.1"), options, ("u", "p", "ref"))
    assert target.device_type == expected


@pytest.mark.parametrize(("override", "expected"), CASES)
def test_discover_network_seed(override, expected) -> None:
    options = discover_options({**discover_config(), "network_driver_override": override})
    device = collect_device("d", "core1", "10.0.0.1")
    assert _seed_target("d", device, options).device_type == expected
