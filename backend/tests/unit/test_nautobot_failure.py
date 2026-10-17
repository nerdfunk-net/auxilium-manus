"""Nautobot errors -> structured FailureInfo, and the steps that record it."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from models.failure import failure_for_step_exception, failure_from_exception
from models.workflow_context import DeviceContext
from services.nautobot.client import NautobotService
from services.nautobot.common.exceptions import (
    NautobotAPIError,
    NautobotDuplicateResourceError,
    NautobotError,
    NautobotNotFoundError,
    NautobotResourceNotFoundError,
    NautobotValidationError,
)
from services.nautobot.credentials import NautobotCredentials
from workflow_steps.check_nautobot_job import executor as check_job
from workflow_steps.exists_in_nautobot import executor as exists_mod

_CREDS = NautobotCredentials(url="http://nautobot.test", token="tok", timeout=5.0)


def _response(status: int, text: str = "") -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.json.return_value = {}
    resp.text = text
    return resp


def _raised(outcome: MagicMock | Exception, *, graphql: bool = False) -> NautobotError:
    svc = NautobotService()
    client = MagicMock()
    for method in ("post", "request"):
        mock = (
            AsyncMock(side_effect=outcome)
            if isinstance(outcome, Exception)
            else AsyncMock(return_value=outcome)
        )
        setattr(client, method, mock)
    svc._client_verify = client
    svc._client_no_verify = client

    async def run() -> NautobotError:
        with patch(
            "services.nautobot.client.validate_source_transport_async",
            return_value="http://nautobot.test",
        ):
            with pytest.raises(NautobotError) as info:
                if graphql:
                    await svc.graphql_query("{ devices { id } }", None, _CREDS)
                else:
                    await svc.rest_request("dcim/devices/", _CREDS)
            return info.value

    return asyncio.run(run())


@pytest.mark.parametrize(
    ("status", "kind", "retryable", "hint"),
    [
        (400, "bad_request", False, "check_request"),
        (401, "auth_failed", False, "check_credentials"),
        (403, "permission_denied", False, "check_permissions"),
        (404, "not_found", False, "check_request"),
        (429, "rate_limited", True, "retry_later"),
        (502, "server_error", True, "check_controller"),
    ],
)
def test_rest_statuses(status: int, kind: str, retryable: bool, hint: str) -> None:
    failure = _raised(_response(status, text="Traceback tok3n")).failure

    assert (failure.kind, failure.http_status, failure.retryable, failure.hint) == (
        kind,
        status,
        retryable,
        hint,
    )
    assert "tok3n" not in failure.model_dump_json()


def test_graphql_status_and_phase() -> None:
    assert _raised(_response(401), graphql=True).failure.phase == "auth"
    assert _raised(_response(503), graphql=True).failure.kind == "server_error"


def test_timeout_and_transport() -> None:
    req = httpx.Request("GET", "http://x")
    timeout = _raised(httpx.ReadTimeout("slow", request=req)).failure
    assert (timeout.kind, timeout.retryable) == ("timeout", True)

    refused = httpx.ConnectError("x", request=req)
    refused.__cause__ = ConnectionRefusedError()
    assert _raised(refused).failure.kind == "refused"


def test_domain_errors() -> None:
    assert NautobotResourceNotFoundError("Location", "HQ").failure.kind == "not_found"
    assert NautobotDuplicateResourceError("Device", "r1").failure.kind == "already_exists"
    assert NautobotNotFoundError("x", http_status=404).failure.kind == "not_found"
    assert NautobotValidationError("x").failure.kind == "bad_request"
    assert NautobotAPIError("x").failure.kind == "unknown"


def test_step_level_record_for_a_raw_client_error() -> None:
    exc = NautobotAPIError("REST request failed", http_status=503)

    failure = failure_for_step_exception(exc, category="internal")

    assert failure is not None
    assert failure.kind == "server_error"
    assert failure_from_exception(exc) is not None


def _parsed(max_checks: int = 1) -> check_job._ParsedConfig:
    return check_job._ParsedConfig(
        source_id="s",
        job_uuid_expr="jr-1",
        max_checks=max_checks,
        interval_seconds=0,
        bag_name="nautobot_job",
    )


def _check(result: dict | Exception, max_checks: int = 1):
    service = AsyncMock()
    if isinstance(result, Exception):
        service.get_job_result = AsyncMock(side_effect=result)
    else:
        service.get_job_result = AsyncMock(return_value=result)
    device = DeviceContext(id="d1", name="d1", hostname="d1")
    _, failed, ok = asyncio.run(
        check_job._check_job_for_device(
            device_key="d1",
            device=device,
            node_id="n",
            jobs_service=service,
            parsed=_parsed(max_checks),
            run_id=None,
        )
    )
    assert not ok
    return failed.errors[0].failure


def test_job_that_ended_unsuccessfully_is_a_task_failure() -> None:
    failure = _check({"status": "FAILURE"})

    assert failure is not None
    assert (failure.phase, failure.kind, failure.retryable) == ("task", "task_failed", False)
    assert (failure.attempts, failure.max_attempts) == (1, 1)


def test_job_that_never_finished_is_a_task_timeout() -> None:
    failure = _check({"status": "STARTED"}, max_checks=2)

    assert failure is not None
    assert (failure.kind, failure.retryable, failure.attempts) == ("task_timeout", True, 2)


def test_job_status_unreachable_keeps_the_api_cause() -> None:
    failure = _check(NautobotAPIError("down", http_status=401))

    assert failure is not None
    assert failure.kind == "auth_failed"


def test_exists_in_nautobot_records_the_failure() -> None:
    device = DeviceContext(id="d1", name="d1", hostname="d1")
    failed = exists_mod._failed(
        device,
        node_id="n",
        code="x",
        message="m",
        failure=NautobotAPIError("x", http_status=403).failure,
    )

    assert failed.errors[0].failure is not None
    assert failed.errors[0].failure.kind == "permission_denied"
