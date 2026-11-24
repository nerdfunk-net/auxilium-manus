"""W6-02 (P-C step 4): the per-device boundary of the Nautobot job and attribute steps.

``start-nautobot-job``, ``check-nautobot-job`` and ``get-nautobot-attributes`` run on
``run_per_device``: any exception fails **that device only** (a started job's id is never lost
because a later device raised), the text of a Nautobot client error is kept (the client sanitises
it) and any other text is reduced to the class name plus a ``FailureInfo``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.nautobot.common.exceptions import (
    NautobotAmbiguousMatchError,
    NautobotAPIError,
)
from tests.unit._step_helpers import (
    call_step,
    make_context,
    make_device,
    make_run,
    patch_object_session,
)
from workflow_steps.check_nautobot_job import executor as check_mod
from workflow_steps.get_nautobot_attributes import executor as attrs_mod
from workflow_steps.start_nautobot_job import executor as start_mod

_SECRET = "s3cr3t-library-text 10.9.9.9"
_JOB = "11111111-1111-1111-1111-111111111111"


def _by_name(outcomes: list[Any]) -> dict[str, Any]:
    return {o.name: o.context for o in outcomes}


# --- start-nautobot-job --------------------------------------------------------------------


async def _start(run_job: AsyncMock, *names: str) -> dict[str, Any]:
    mod = "workflow_steps.start_nautobot_job.executor"
    jobs = MagicMock()
    jobs.run_job = run_job
    config = {
        "nautobot_source_id": "src",
        "job_id": "job-1",
        "parameters": {"required": {}, "optional": {}},
        "max_concurrency": 1,
    }
    with (
        patch_object_session(mod),
        patch(f"{mod}.resolve_nautobot_credentials"),
        patch(f"{mod}.CredentialsBoundNautobotClient"),
        patch(f"{mod}.service_factory"),
        patch(f"{mod}.NautobotJobsService", return_value=jobs),
        patch(f"{mod}.DeviceCommonService"),
    ):
        outcomes = await call_step(
            start_mod.execute,
            config,
            make_context([make_device(n) for n in names]),
            run=make_run(),
        )
    return _by_name(outcomes)


def _job_result(job_id: str) -> dict[str, Any]:
    return {"job_result": {"id": job_id}}


@pytest.mark.asyncio
async def test_a_job_start_that_raises_unexpectedly_keeps_the_jobs_already_started() -> None:
    calls = 0

    async def run_job(job_id: str, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 3:
            raise OSError(_SECRET)
        return _job_result(f"jr-{calls}")

    out = await _start(AsyncMock(side_effect=run_job), "a", "b", "c")

    assert list(out["success"].devices) == ["a", "b"]
    error = out["failure"].devices["c"].errors[-1]
    assert error.message == "OSError"
    assert error.failure is not None
    started = out["success"].devices["b"].attribute_bags["nautobot_job"]
    assert started["job_result_id"] == "jr-2"


@pytest.mark.asyncio
async def test_an_ambiguous_match_fails_that_device_with_the_client_text() -> None:
    calls = 0

    async def run_job(job_id: str, **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise NautobotAmbiguousMatchError("2 devices named x")
        return _job_result("jr-1")

    out = await _start(AsyncMock(side_effect=run_job), "a", "b")

    assert list(out["success"].devices) == ["a"]
    assert out["failure"].devices["b"].errors[-1].message == "2 devices named x"


@pytest.mark.asyncio
async def test_a_failed_start_still_records_the_request() -> None:
    out = await _start(AsyncMock(side_effect=OSError(_SECRET)), "a")

    failed = out["failure"].devices["a"]
    assert failed.requests["node-1"][0].ok is False


# --- check-nautobot-job --------------------------------------------------------------------


async def _check(get_job_result: AsyncMock, *names: str) -> dict[str, Any]:
    mod = "workflow_steps.check_nautobot_job.executor"
    jobs = MagicMock()
    jobs.get_job_result = get_job_result
    config = {
        "nautobot_source_id": "src",
        "job_uuid": _JOB,
        "max_checks": 1,
        "interval_seconds": 0,
    }
    with (
        patch_object_session(mod),
        patch(f"{mod}.resolve_nautobot_credentials"),
        patch(f"{mod}.CredentialsBoundNautobotClient"),
        patch(f"{mod}.service_factory"),
        patch(f"{mod}.NautobotJobsService", return_value=jobs),
    ):
        outcomes = await call_step(
            check_mod.execute,
            config,
            make_context([make_device(n) for n in names]),
            run=make_run(),
        )
    return _by_name(outcomes)


@pytest.mark.asyncio
async def test_an_unexpected_error_while_checking_fails_that_device_only() -> None:
    async def get_job_result(job_uuid: str) -> dict[str, Any]:
        if get_job_result.calls:  # type: ignore[attr-defined]
            raise KeyError(_SECRET)
        get_job_result.calls += 1  # type: ignore[attr-defined]
        return {"status": "SUCCESS"}

    get_job_result.calls = 0  # type: ignore[attr-defined]
    out = await _check(AsyncMock(side_effect=get_job_result), "a", "b")

    assert list(out["success"].devices) == ["a"]
    error = out["failure"].devices["b"].errors[-1]
    assert error.message == "KeyError"
    assert error.failure is not None


@pytest.mark.asyncio
async def test_an_api_error_is_polled_as_before_and_reported_with_its_text() -> None:
    out = await _check(AsyncMock(side_effect=NautobotAPIError("Nautobot returned 502")), "a")

    error = out["failure"].devices["a"].errors[-1]
    assert "could not determine job status after 1 check(s)" in error.message
    assert "Nautobot returned 502" in error.message


# --- get-nautobot-attributes ---------------------------------------------------------------


async def _attrs(graphql: Any, *names: str) -> dict[str, Any]:
    service = MagicMock()
    service.graphql_query = graphql
    with (
        patch.object(attrs_mod, "_bind_nautobot", return_value=(MagicMock(), service)),
        patch.object(attrs_mod, "device_query_for_groups", AsyncMock(return_value="query")),
        patch.object(
            attrs_mod,
            "resolve_nautobot_device_id",
            AsyncMock(side_effect=lambda **kw: "nb-" + kw["device"].id),
        ),
    ):
        outcomes = await call_step(
            attrs_mod.execute,
            {"nautobot_source_id": "s"},
            make_context([make_device(n) for n in names]),
            run=make_run(),
        )
    return _by_name(outcomes)


@pytest.mark.asyncio
async def test_attributes_hides_the_text_of_an_unexpected_error_but_keeps_the_clients() -> None:
    async def graphql(query, variables, credentials, *, strict=False):
        if variables["deviceId"] == "nb-b":
            raise KeyError(_SECRET)
        if variables["deviceId"] == "nb-c":
            raise NautobotAPIError("Nautobot returned 502")
        return {"data": {"device": {"id": variables["deviceId"], "name": "x"}}}

    out = await _attrs(graphql, "a", "b", "c")

    assert list(out["success"].devices) == ["a"]
    hidden = out["failure"].devices["b"].errors[-1]
    assert (hidden.code, hidden.message) == ("keyerror", "KeyError")
    assert hidden.failure is not None
    assert out["failure"].devices["c"].errors[-1].message == "Nautobot returned 502"


@pytest.mark.asyncio
async def test_a_failed_start_redacts_a_secret_in_the_response_it_keeps() -> None:
    device = start_mod._device_after_failed_start(
        make_device("a"),
        node_id="n",
        bag_name="nautobot_job",
        response={"detail": "nope", "password": "hunter2"},
    )

    assert device.attribute_bags["nautobot_job"]["response"]["password"] != "hunter2"


@pytest.mark.asyncio
async def test_a_client_error_outside_the_poll_loop_keeps_its_text() -> None:
    out = await _check(
        AsyncMock(side_effect=NautobotAmbiguousMatchError("job result does not exist")), "a"
    )

    error = out["failure"].devices["a"].errors[-1]
    assert error.message == "job result does not exist"


@pytest.mark.asyncio
async def test_an_unsuccessful_job_keeps_what_the_check_learned_on_the_failed_device() -> None:
    out = await _check(AsyncMock(return_value={"status": "FAILURE"}), "a")

    failed = out["failure"].devices["a"]
    assert failed.attribute_bags["nautobot_job"]["status"] == "FAILURE"
    assert failed.errors[-1].code == "job_check_failed"


@pytest.mark.asyncio
async def test_attributes_without_detail_data_is_not_found() -> None:
    async def graphql(query, variables, credentials, *, strict=False):
        return {"data": {"device": None}}

    out = await _attrs(graphql, "a")

    error = out["failure"].devices["a"].errors[-1]
    assert error.code == "not_found"
    assert error.message == "No Nautobot data returned for device a"
