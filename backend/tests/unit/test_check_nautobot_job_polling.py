"""check-nautobot-job: config bounds, the polling loop and the execute path (P-T, W13-12).

The step was 73 % covered; the lifts below are the scenarios a refactoring of the per-device
boundary and of the Nautobot preamble (P-C, P-F) must not change: bounds, retry count,
failure kinds (`task_failed` / `task_timeout` / API error) and credential binding.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.workflow_context import DeviceStatus
from services.nautobot.common.exceptions import NautobotAPIError
from tests.unit._step_helpers import (
    call_step,
    make_context,
    make_device,
    make_run,
    patch_object_session,
    settle,
)
from workflow_steps.check_nautobot_job import executor as mod

_JOB = "11111111-1111-1111-1111-111111111111"
_JOB_2 = "22222222-2222-2222-2222-222222222222"

_MOD = "workflow_steps.check_nautobot_job.executor"


def _parsed(**overrides: Any) -> Any:
    values = {
        "source_id": "src",
        "job_uuid_expr": _JOB,
        "max_checks": 3,
        "interval_seconds": 0,
        "bag_name": "nautobot_job",
    }
    return mod._ParsedConfig(**{**values, **overrides})


async def _check(results: list[Any], parsed: Any = None) -> tuple[Any, bool, AsyncMock]:
    service = MagicMock()
    service.get_job_result = AsyncMock(side_effect=results)
    with patch(f"{_MOD}.asyncio.sleep", new=AsyncMock()):
        original = make_device("d1")
        device, ok = settle(
            await mod._check_job_for_device(
                device=original, jobs_service=service, parsed=parsed or _parsed(), run_id=None
            ),
            original,
        )
    return device, ok, service.get_job_result


# ── config ─────────────────────────────────────────────────────────────────────────────────────


def test_defaults_parse() -> None:
    parsed = mod._parse_config({"nautobot_source_id": "src", "job_uuid": "jr"})

    assert parsed.max_checks >= 1 and parsed.interval_seconds >= 0
    assert parsed.bag_name


@pytest.mark.parametrize(
    ("config", "message"),
    [
        ({"nautobot_source_id": " ", "job_uuid": "j"}, "nautobot_source_id is required"),
        ({"nautobot_source_id": "s", "job_uuid": " "}, "job_uuid is required"),
        (
            {"nautobot_source_id": "s", "job_uuid": "j", "max_checks": "x"},
            "max_checks must be a whole number",
        ),
        (
            {"nautobot_source_id": "s", "job_uuid": "j", "max_checks": 0},
            "max_checks must be between 1",
        ),
        (
            {"nautobot_source_id": "s", "job_uuid": "j", "interval_seconds": "x"},
            "interval_seconds must be a whole number",
        ),
        (
            {"nautobot_source_id": "s", "job_uuid": "j", "interval_seconds": -1},
            "interval_seconds must be between 0",
        ),
        (
            {
                "nautobot_source_id": "s",
                "job_uuid": "j",
                "max_checks": 100,
                "interval_seconds": 100,
            },
            "ceiling",
        ),
    ],
)
def test_bad_config_is_a_value_error(config: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        mod._parse_config(config)


# ── polling ────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_job_that_finishes_after_polling_succeeds() -> None:
    device, ok, calls = await _check(
        [{"status": "PENDING"}, {"status": "STARTED"}, {"status": "SUCCESS"}]
    )

    assert ok and device.attribute_bags["nautobot_job"]["checks_performed"] == 3
    assert calls.await_count == 3


@pytest.mark.asyncio
async def test_a_failed_job_stops_polling_and_is_not_retryable() -> None:
    device, ok, calls = await _check([{"status": "FAILURE"}])

    error = device.errors[-1]
    assert not ok and calls.await_count == 1
    assert error.failure.kind == "task_failed" and not error.failure.retryable


@pytest.mark.asyncio
async def test_a_job_still_running_after_all_checks_is_a_retryable_timeout() -> None:
    device, ok, calls = await _check([{"status": "STARTED"}] * 3)

    error = device.errors[-1]
    assert not ok and calls.await_count == 3
    assert error.failure.kind == "task_timeout" and error.failure.retryable
    assert "may complete later" in error.message


@pytest.mark.asyncio
async def test_a_persistent_api_error_reports_that_the_status_is_unknown() -> None:
    device, ok, _calls = await _check([NautobotAPIError("502")] * 3)

    assert not ok
    assert "could not determine job status after 3 check(s)" in device.errors[-1].message


@pytest.mark.asyncio
async def test_an_api_error_followed_by_success_still_succeeds() -> None:
    _device, ok, calls = await _check([NautobotAPIError("502"), {"status": "SUCCESS"}])

    assert ok and calls.await_count == 2


@pytest.mark.asyncio
async def test_a_missing_status_never_reaches_a_terminal_state() -> None:
    device, ok, _calls = await _check([{}] * 3)

    assert not ok
    assert "did not reach a terminal state" in device.errors[-1].message


@pytest.mark.asyncio
async def test_an_unresolved_job_uuid_fails_the_device_without_polling() -> None:
    service = MagicMock()
    service.get_job_result = AsyncMock()

    original = make_device("d1")
    device, ok = settle(
        await mod._check_job_for_device(
            device=original,
            jobs_service=service,
            parsed=_parsed(job_uuid_expr="{custom.missing}"),
            run_id=None,
        ),
        original,
    )

    assert not ok and device.status == DeviceStatus.FAILED
    service.get_job_result.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "hostile", ["x/../../dcim/devices/?limit=1", "jr-1", _JOB + "/"]
)
async def test_a_job_id_that_is_not_a_uuid_never_reaches_the_rest_path(hostile: str) -> None:
    """W6-10: the value comes from device data and is put into ``/api/extras/job-results/<id>/``."""
    service = MagicMock()
    service.get_job_result = AsyncMock()

    original = make_device("d1", attribute_bags={"custom": {"job": hostile}})
    device, ok = settle(
        await mod._check_job_for_device(
            device=original,
            jobs_service=service,
            parsed=_parsed(job_uuid_expr="{custom.job}"),
            run_id=None,
        ),
        original,
    )

    assert not ok and device.status == DeviceStatus.FAILED
    error = device.errors[-1]
    assert error.failure is not None and error.failure.kind == "bad_request"
    assert hostile not in error.message
    assert error.code == "job_uuid_invalid"
    service.get_job_result.assert_not_awaited()


# ── execute ────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_binds_the_source_credentials_and_routes_by_status() -> None:
    jobs = MagicMock()
    jobs.get_job_result = AsyncMock(side_effect=[{"status": "SUCCESS"}, {"status": "FAILURE"}])
    with (
        patch_object_session(),
        patch("workflow_steps.common.nautobot_step.resolve_nautobot_credentials") as credentials,
        patch("workflow_steps.common.nautobot_step.CredentialsBoundNautobotClient"),
        patch("workflow_steps.common.nautobot_step.service_factory"),
        patch(f"{_MOD}.NautobotJobsService", return_value=jobs),
    ):
        outcomes = await call_step(
            mod.execute,
            {"nautobot_source_id": "src", "job_uuid": _JOB, "max_checks": 1},
            make_context([make_device("a"), make_device("b")]),
            run=make_run(),
        )

    credentials.assert_called_once()
    assert credentials.call_args.args[1] == "src"
    assert sorted(o.name for o in outcomes) == ["failure", "success"]


@pytest.mark.asyncio
async def test_execute_without_devices_is_a_no_op_success() -> None:
    outcomes = await call_step(
        mod.execute, {"nautobot_source_id": "s", "job_uuid": "j"}, make_context()
    )

    assert [o.name for o in outcomes] == ["success"]


@pytest.mark.asyncio
async def test_execute_without_a_db_session_is_a_runtime_error() -> None:
    with patch("workflow_steps.common.run_session.object_session", return_value=None):
        with pytest.raises(RuntimeError, match="no active DB session"):
            await call_step(
                mod.execute,
                {"nautobot_source_id": "s", "job_uuid": "j"},
                make_context([make_device("a")]),
            )
