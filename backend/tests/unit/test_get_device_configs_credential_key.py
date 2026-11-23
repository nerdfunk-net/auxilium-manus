"""get-device-configs: the credential the session pool is keyed by (W3b-01).

The pool key holds the *reference* of the credential (never the secret). With
``credential_source: run_param`` the reference comes from the run inputs; the step resolves it
for the login and hands the pool the same resolved reference, so two nodes with different
credentials never share a live session (W3b-01).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.network.netmiko.connection import ConfigResult
from tests.unit._step_helpers import (
    call_step,
    make_context,
    make_device,
    make_run,
    patch_object_session,
    patch_ssh_credential,
)
from workflow_steps.get_device_configs.executor import execute

_MOD = "workflow_steps.get_device_configs.executor"


async def _run(config: dict, run_inputs: dict) -> tuple[AsyncMock, AsyncMock]:
    device = make_device("a", primary_ip4="10.0.0.1/24", network_driver="cisco_ios")
    with (
        patch_ssh_credential(_MOD) as credential,
        patch_object_session(_MOD),
        patch(f"{_MOD}.NetmikoService") as netmiko_cls,
    ):
        netmiko_cls.return_value.get_configs = AsyncMock(
            return_value=ConfigResult(success=True, running_config="hostname a\n")
        )
        await call_step(
            execute,
            {"config_format": "running", **config},
            make_context([device]),
            run=make_run(run_inputs=run_inputs),
        )
    return credential, netmiko_cls.return_value.get_configs


@pytest.mark.asyncio
async def test_a_literal_reference_is_used_for_login_and_pool_key() -> None:
    credential, get_configs = await _run({"credential_reference": "lab-ssh"}, {})

    assert credential.call_args.args[1] == "lab-ssh"
    assert get_configs.call_args.kwargs["credential_reference"] == "lab-ssh"


@pytest.mark.asyncio
async def test_a_run_param_reference_is_used_for_the_login() -> None:
    credential, _get_configs = await _run(
        {"credential_source": "run_param", "credential_param": "cred"}, {"cred": "from-run"}
    )

    assert credential.call_args.args[1] == "from-run"


@pytest.mark.asyncio
async def test_a_run_param_reference_is_the_pool_key() -> None:
    _credential, get_configs = await _run(
        {"credential_source": "run_param", "credential_param": "cred"}, {"cred": "from-run"}
    )

    assert get_configs.call_args.kwargs["credential_reference"] == "from-run"
