"""ISE errors -> FailureInfo, and step-level failures reaching the step result."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from models.failure import FailureInfo, failure_from_exception, failure_to_json
from models.workflow_context import StepOutcome, WorkflowContext
from services.execution.step_runner.runner import _outcome_failure
from services.ise.client import ISEService
from services.ise.common.exceptions import ISEAPIError, ISEError, ISEValidationError
from services.ise.credentials import ISECredentials
from workflow_steps.update_ise_tacacs_key.executor import _preflight_ise


def _creds() -> ISECredentials:
    return ISECredentials(base_url="https://10.10.20.77", username="admin", password="pw")


def _raised(response_or_error: httpx.Response | Exception) -> ISEError:
    service = ISEService()
    client = AsyncMock()
    if isinstance(response_or_error, Exception):
        client.request.side_effect = response_or_error
    else:
        client.request.return_value = response_or_error
    service._client_verify = client
    service._client_no_verify = client

    async def run() -> ISEError:
        with pytest.raises(ISEError) as info:
            await service.ers_request("networkdevice", _creds())
        return info.value

    return asyncio.run(run())


@pytest.mark.parametrize(
    ("status", "kind", "retryable", "hint"),
    [
        (401, "auth_failed", False, "check_credentials"),
        (403, "permission_denied", False, "check_permissions"),
        (404, "not_found", False, "check_request"),
        (400, "bad_request", False, "check_request"),
        (429, "rate_limited", True, "retry_later"),
        (503, "server_error", True, "check_controller"),
    ],
)
def test_http_statuses(status: int, kind: str, retryable: bool, hint: str) -> None:
    failure = _raised(httpx.Response(status, text="Traceback secret")).failure

    assert (failure.kind, failure.http_status, failure.retryable, failure.hint) == (
        kind,
        status,
        retryable,
        hint,
    )
    assert "secret" not in failure.model_dump_json()


def test_auth_failure_is_in_the_auth_phase() -> None:
    assert _raised(httpx.Response(401)).failure.phase == "auth"
    assert _raised(httpx.Response(500)).failure.phase == "api"


def test_timeout_and_transport() -> None:
    req = httpx.Request("GET", "https://x")
    timeout = _raised(httpx.ReadTimeout("slow", request=req)).failure
    assert (timeout.kind, timeout.retryable) == ("timeout", True)

    refused = httpx.ConnectError("x", request=req)
    refused.__cause__ = ConnectionRefusedError()
    assert _raised(refused).failure.kind == "refused"
    assert _raised(RuntimeError("boom")).failure.kind == "unknown"


def test_plain_exceptions_are_unknown() -> None:
    assert ISEAPIError("x").failure.kind == "unknown"
    assert ISEValidationError("x").failure.kind == "bad_request"


def test_failure_survives_wrapping_in_runtime_error() -> None:
    try:
        try:
            raise ISEAPIError("down", http_status=401)
        except ISEAPIError as exc:
            raise RuntimeError("get-ise-devices: ISE request failed") from exc
    except RuntimeError as wrapped:
        failure = failure_from_exception(wrapped)

    assert failure is not None
    assert failure.kind == "auth_failed"
    assert failure_from_exception(RuntimeError("plain")) is None


def test_preflight_outcome_carries_the_failure() -> None:
    service = SimpleNamespace(
        test_connection=AsyncMock(side_effect=ISEAPIError("x", http_status=503))
    )
    context = WorkflowContext(run_id="r", workflow_id="w")

    outcomes = asyncio.run(_preflight_ise(service, "ise-1", context))

    assert outcomes is not None
    assert outcomes[0].failure is not None
    assert outcomes[0].failure.kind == "server_error"


def test_outcome_failure_is_persisted_json() -> None:
    context = WorkflowContext(run_id="r", workflow_id="w")
    info = FailureInfo(phase="api", kind="timeout", retryable=True)
    outcomes = [
        StepOutcome(name="success", context=context),
        StepOutcome(name="failure", context=context, failure=info),
    ]

    assert _outcome_failure(outcomes) == failure_to_json(info)
    assert _outcome_failure(outcomes) == {
        "phase": "api",
        "kind": "timeout",
        "retryable": True,
    }
    assert _outcome_failure(outcomes[:1]) is None
