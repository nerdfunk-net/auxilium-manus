"""Catalyst Center errors -> structured, non-sensitive FailureInfo."""

from __future__ import annotations

import asyncio
import ssl

import httpx
import pytest

from models.catalyst_center import CatalystCenterCommandResult, CatalystCenterCommandStatus
from models.failure import FailureInfo
from models.workflow_context import DeviceContext
from services.catalyst_center.client import CatalystCenterService
from services.catalyst_center.common.exceptions import (
    CatalystCenterAPIError,
    CatalystCenterError,
    CatalystCenterTaskError,
)
from tests.unit.test_catalyst_center_client import _Controller, _creds
from workflow_steps.common.catalyst_center_facts import (
    FactError,
    _with_entries,
    error_entry,
    ok_entry,
)
from workflow_steps.run_catalyst_center_command.executor import _command_failure


def _call(controller: _Controller, **setup: object) -> CatalystCenterError:
    for key, value in setup.items():
        setattr(controller, key, value)

    async def run() -> CatalystCenterError:
        http = httpx.AsyncClient(transport=httpx.MockTransport(controller.handler))
        service = CatalystCenterService()
        service._client_verify = http
        service._client_no_verify = http
        try:
            with pytest.raises(CatalystCenterError) as info:
                await service.request(_creds(), "GET", "/a")
            return info.value
        finally:
            await http.aclose()

    return asyncio.run(run())


@pytest.mark.parametrize(
    ("setup", "phase", "kind", "status", "retryable", "hint"),
    [
        ({"auth_status": 401}, "auth", "auth_failed", 401, False, "check_credentials"),
        ({"auth_status": 500}, "api", "server_error", 500, True, "check_controller"),
        (
            {"api_responses": [httpx.Response(401), httpx.Response(401)]},
            "api",
            "permission_denied",
            401,
            False,
            "check_permissions",
        ),
        (
            {"api_responses": [httpx.Response(403)]},
            "api",
            "permission_denied",
            403,
            False,
            "check_permissions",
        ),
        ({"api_responses": [httpx.Response(404)]}, "api", "not_found", 404, False, "check_request"),
        (
            {"api_responses": [httpx.Response(400)]},
            "api",
            "bad_request",
            400,
            False,
            "check_request",
        ),
        (
            {"api_responses": [httpx.Response(502, text="Traceback secret")]},
            "api",
            "server_error",
            502,
            True,
            "check_controller",
        ),
        (
            {"api_responses": [httpx.Response(200, text="<html>")]},
            "api",
            "invalid_response",
            200,
            False,
            "check_controller",
        ),
    ],
)
def test_http_responses(setup, phase, kind, status, retryable, hint) -> None:
    exc = _call(_Controller(), **setup)

    failure = exc.failure
    assert (failure.phase, failure.kind, failure.http_status) == (phase, kind, status)
    assert (failure.retryable, failure.hint) == (retryable, hint)
    assert "Traceback" not in failure.model_dump_json()
    assert "secret" not in failure.model_dump_json()


def _transport_failure(error: Exception) -> FailureInfo:
    def boom(request: httpx.Request) -> httpx.Response:
        raise error

    async def run() -> CatalystCenterAPIError:
        service = CatalystCenterService()
        service._client_verify = httpx.AsyncClient(transport=httpx.MockTransport(boom))
        with pytest.raises(CatalystCenterAPIError) as info:
            await service.request(_creds(), "GET", "/a")
        return info.value

    return asyncio.run(run()).failure


def _chained(error: Exception, cause: BaseException) -> Exception:
    error.__cause__ = cause
    return error


def test_transport_failures() -> None:
    req = httpx.Request("GET", "https://x")
    assert _transport_failure(httpx.ReadTimeout("slow", request=req)).kind == "timeout"
    assert _transport_failure(httpx.ReadTimeout("slow", request=req)).retryable
    assert (
        _transport_failure(
            _chained(httpx.ConnectError("x", request=req), ConnectionRefusedError())
        ).kind
        == "refused"
    )
    assert (
        _transport_failure(
            _chained(httpx.ConnectError("x", request=req), ssl.SSLCertVerificationError("self"))
        ).kind
        == "tls_error"
    )
    assert _transport_failure(httpx.ConnectError("x", request=req)).kind == "unknown"


def test_rate_limit_after_bounded_retries() -> None:
    controller = _Controller()
    controller.api_responses = [httpx.Response(429, headers={"Retry-After": "0"})] * 4

    async def run() -> CatalystCenterError:
        http = httpx.AsyncClient(transport=httpx.MockTransport(controller.handler))
        service = CatalystCenterService()
        service._client_verify = http

        async def no_sleep(_: float) -> None:
            return None

        service._sleep = no_sleep  # type: ignore[method-assign]
        with pytest.raises(CatalystCenterError) as info:
            await service.request(_creds(), "GET", "/a")
        return info.value

    failure = asyncio.run(run()).failure
    assert (failure.kind, failure.http_status, failure.retryable) == ("rate_limited", 429, True)
    assert failure.hint == "retry_later"


@pytest.mark.parametrize(
    ("code", "kind", "retryable"),
    [
        ("task_failed", "task_failed", False),
        ("task_timeout", "task_timeout", True),
        ("invalid_response", "invalid_response", False),
    ],
)
def test_task_errors(code: str, kind: str, retryable: bool) -> None:
    failure = CatalystCenterTaskError("anything", code=code).failure

    assert (failure.phase, failure.kind, failure.retryable) == ("task", kind, retryable)


def test_unclassified_error_is_unknown() -> None:
    assert CatalystCenterError("x").failure.kind == "unknown"


def _result(status: CatalystCenterCommandStatus) -> CatalystCenterCommandResult:
    return CatalystCenterCommandResult(device_id="d", command="show x", status=status, output="o")


def test_command_failure_prefers_blocklisted() -> None:
    results = {
        "show a": _result(CatalystCenterCommandStatus.FAILURE),
        "show b": _result(CatalystCenterCommandStatus.BLOCKLISTED),
    }

    assert _command_failure(results, ("show a", "show b")).kind == "command_blocked"
    assert _command_failure({"show a": results["show a"]}, ("show a",)).kind == "command_error"
    assert _command_failure({}, ("show a",)).kind == "command_error"


def test_fact_failure_reaches_the_device_error_but_not_the_parsed_shape() -> None:
    info = FailureInfo(phase="api", kind="timeout", retryable=True)
    device = DeviceContext(id="d1", name="sw1", hostname="sw1")
    entries = {
        "interfaces": error_entry(FactError("timed out", info)),
        "vlans": error_entry("plain text"),
    }

    updated, ok = _with_entries(device, entries, output_key="cc", step_id="s", node_id="n")

    assert not ok
    assert updated.errors[0].failure == info
    assert updated.parsed["cc"]["interfaces"] == {"parsed": None, "error": "timed out"}


def test_partial_fact_failure_does_not_fail_the_device() -> None:
    device = DeviceContext(id="d1", name="sw1", hostname="sw1")
    entries = {"interfaces": error_entry(FactError("x", None)), "vlans": ok_entry([1])}

    updated, ok = _with_entries(device, entries, output_key="cc", step_id="s", node_id="n")

    assert ok
    assert updated.errors == []
