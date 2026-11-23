"""Catalyst Center steps: a non-controller exception on one device (P-T, W8-01, W8-18 (1)).

Only the controller's own error family is caught per device; an artifact-store error, a parse
error or a bug leaves the per-device boundary and ends the step, discarding the devices that
were already done. Each test injects one such exception for one device and expects that device
to fail while the others still succeed.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.exc import OperationalError

from models.catalyst_center import CatalystCenterCommandResult, CatalystCenterCommandStatus
from models.workflow_context import DeviceStatus
from services.artifacts import InMemoryArtifactService
from tests.unit._step_helpers import (
    call_step,
    make_context,
    patch_object_session,
    strict_xfail,
)
from tests.unit.test_get_catalyst_center_client_data_executor import _client
from tests.unit.test_get_catalyst_center_client_data_executor import _device as _client_device
from tests.unit.test_get_catalyst_center_client_data_executor import _Env as _ClientEnv
from tests.unit.test_get_catalyst_center_configs_executor import _device as _config_device
from tests.unit.test_get_catalyst_center_configs_executor import _Harness as _ConfigsHarness
from tests.unit.test_run_catalyst_center_command_executor import _device as _command_device
from tests.unit.test_run_catalyst_center_command_executor import _Harness as _CommandHarness
from workflow_steps.get_catalyst_center_client_data.executor import execute as client_data
from workflow_steps.get_catalyst_center_configs.executor import execute as configs
from workflow_steps.run_catalyst_center_command.executor import execute as run_command

_ERRORS = [RuntimeError("store down"), OSError("disk gone"), KeyError("unexpected payload")]


def _split(outcomes: list[Any]) -> dict[str, dict[str, Any]]:
    return {o.name: o.context.devices for o in outcomes}


# --- get-catalyst-center-configs ---------------------------------------------------------------


async def _run_configs(*, fetch: Any, artifacts: InMemoryArtifactService | None = None) -> Any:
    with _ConfigsHarness(fetch):
        return await call_step(
            configs,
            {},
            make_context([_config_device("a"), _config_device("b")]),
            artifact_service=artifacts or InMemoryArtifactService(),
        )


@pytest.mark.asyncio
async def test_configs_both_devices_succeed_without_errors() -> None:
    outcomes = await _run_configs(fetch=AsyncMock(return_value="hostname x"))

    assert set(_split(outcomes)["success"]) == {"a", "b"}


@strict_xfail("W8-01", "get_device_config() errors other than the controller family escape")
@pytest.mark.asyncio
@pytest.mark.parametrize("error", _ERRORS)
async def test_configs_unexpected_fetch_error_fails_only_that_device(error: Exception) -> None:
    async def fetch(device_id: str) -> str:
        if device_id == "a":
            raise error
        return "hostname b"

    by_name = _split(await _run_configs(fetch=fetch))

    assert set(by_name["success"]) == {"b"}
    assert by_name["failure"]["a"].status == DeviceStatus.FAILED


@strict_xfail("W8-01", "artifact_service.store() runs outside the per-device try (E5b)")
@pytest.mark.asyncio
@pytest.mark.parametrize("error", _ERRORS)
async def test_configs_store_error_fails_only_that_device(error: Exception) -> None:
    artifacts = InMemoryArtifactService()
    real_store = artifacts.store

    async def store(**kwargs: Any) -> Any:
        if kwargs["device_id"] == "a":
            raise error
        return await real_store(**kwargs)

    artifacts.store = store  # type: ignore[method-assign]
    by_name = _split(await _run_configs(fetch=AsyncMock(return_value="x"), artifacts=artifacts))

    assert set(by_name["success"]) == {"b"}
    assert by_name["failure"]["a"].status == DeviceStatus.FAILED


# --- run-catalyst-center-command ---------------------------------------------------------------

_COMMAND_CONFIG = {"commands": ["show version"]}


def _ok_results(*device_ids: str) -> AsyncMock:
    return AsyncMock(
        return_value=tuple(
            CatalystCenterCommandResult(
                device_id=d,
                command="show version",
                status=CatalystCenterCommandStatus.SUCCESS,
                output="IOS",
            )
            for d in device_ids
        )
    )


async def _run_command(
    *, run_commands: Any, artifacts: InMemoryArtifactService | None = None
) -> Any:
    with (
        _CommandHarness(run_commands=run_commands),
        patch_object_session("workflow_steps.run_catalyst_center_command.executor"),
    ):
        return await call_step(
            run_command,
            dict(_COMMAND_CONFIG),
            make_context([_command_device("a"), _command_device("b")]),
            artifact_service=artifacts or InMemoryArtifactService(),
        )


@pytest.mark.asyncio
async def test_command_both_devices_succeed_without_errors() -> None:
    outcomes = await _run_command(run_commands=_ok_results("a", "b"))

    assert set(_split(outcomes)["success"]) == {"a", "b"}


@strict_xfail("W8-01", "run_commands() errors other than the controller family escape the chunk")
@pytest.mark.asyncio
@pytest.mark.parametrize("error", _ERRORS)
async def test_command_unexpected_request_error_fails_the_chunk_not_the_step(
    error: Exception,
) -> None:
    outcomes = await _run_command(run_commands=AsyncMock(side_effect=error))

    by_name = _split(outcomes)
    assert set(by_name["failure"]) == {"a", "b"}
    assert all(d.status == DeviceStatus.FAILED for d in by_name["failure"].values())


@strict_xfail("W8-01", "artifact_service.store() in _record_device is outside the chunk boundary")
@pytest.mark.asyncio
@pytest.mark.parametrize("error", _ERRORS)
async def test_command_store_error_fails_only_that_device(error: Exception) -> None:
    artifacts = InMemoryArtifactService()
    real_store = artifacts.store

    async def store(**kwargs: Any) -> Any:
        if kwargs["device_id"] == "a":
            raise error
        return await real_store(**kwargs)

    artifacts.store = store  # type: ignore[method-assign]
    by_name = _split(await _run_command(run_commands=_ok_results("a", "b"), artifacts=artifacts))

    assert set(by_name["success"]) == {"b"}
    assert by_name["failure"]["a"].status == DeviceStatus.FAILED


# --- get-catalyst-center-client-data -----------------------------------------------------------


async def _run_client_data(env: Any) -> Any:
    with env:
        return await call_step(
            client_data, {}, make_context([_client_device("a")]), artifact_service=None
        )


@strict_xfail(
    "W8-01", "no catch-all: an unexpected exception from the query ends the step (twin W8-04)"
)
@pytest.mark.asyncio
@pytest.mark.parametrize("error", _ERRORS)
async def test_client_data_unexpected_query_error_fails_the_device(error: Exception) -> None:
    by_name = _split(await _run_client_data(_ClientEnv(service_error=error)))

    assert by_name["failure"]["a"].status == DeviceStatus.FAILED


@pytest.mark.asyncio
async def test_client_data_sqlalchemy_error_keeps_only_the_class_name() -> None:
    env = _ClientEnv(
        [_client()],
        store_error=OperationalError("INSERT INTO client_mac_addresses ...", {"p": "secret"}, None),
    )
    by_name = _split(await _run_client_data(env))

    error = by_name["failure"]["a"].errors[-1]
    assert error.code == "storage_failed"
    assert "INSERT" not in error.message and "secret" not in error.message
    assert error.failure is not None and error.failure.exception_type == "OperationalError"
