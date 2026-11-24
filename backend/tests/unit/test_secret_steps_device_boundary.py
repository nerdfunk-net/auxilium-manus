"""secret-get / secret-set / secret-generate: what one device's failure does to the others.

A failure that is not a ``SecretManagerError`` is a failure of that device only, and its text is
never stored (the per-device runner, D1, W10-09). Connection loss aborts the step and keeps the
devices already done. Written first in P-T, the two unexpected-error tests were strict xfails
until the secret trio moved onto ``run_per_device``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.workflow_context import DeviceStatus
from services.secret_manager.exceptions import SecretManagerError
from tests.unit._step_helpers import (
    call_step,
    make_context,
    make_device,
    make_run,
    patch_object_session,
)
from workflow_steps.common import secret_manager_step as shared
from workflow_steps.secret_generate import executor as generate_mod
from workflow_steps.secret_get import executor as get_mod
from workflow_steps.secret_set import executor as set_mod

_SECRET = "never-in-a-message-0123456789"


@dataclass(frozen=True)
class _Case:
    module: Any
    method: str
    config: dict[str, Any]
    ok_result: Any
    run_input: bool = False


_CASES = {
    "secret-get": _Case(get_mod, "get_field", {"connection_id": 1}, _SECRET),
    "secret-set": _Case(set_mod, "set_field", {"connection_id": 1}, None, run_input=True),
    "secret-generate": _Case(generate_mod, "generate_field", {"connection_id": 1}, (1, _SECRET)),
}


def _context() -> Any:
    bags = {"run_input": {"new_tacacs_key": "a-new-key-value-12345"}}
    return make_context(
        [make_device("a", attribute_bags=bags), make_device("b", attribute_bags=bags)]
    )


def _service(case: _Case, side_effect: Callable[..., Any]) -> MagicMock:
    service = MagicMock()
    setattr(service, case.method, AsyncMock(side_effect=side_effect))
    return service


async def _run(case: _Case, service: MagicMock) -> Any:
    with (
        patch_object_session(),
        patch.object(shared, "SecretManagerService", return_value=service),
    ):
        return await call_step(case.module.execute, case.config, _context(), run=make_run())


def _fails_nth_device(case: _Case, error: Exception, nth: int = 1) -> Callable[..., Any]:
    """Succeed for every device except the ``nth`` (1-based) one, which raises ``error``."""
    calls: list[str] = []

    def side_effect(connection_id: int, path: str, *_args: Any, **_kwargs: Any) -> Any:
        calls.append(path)
        if len(calls) == nth:
            raise error
        return case.ok_result

    return side_effect


@pytest.mark.asyncio
@pytest.mark.parametrize("step", list(_CASES))
async def test_all_devices_succeed(step: str) -> None:
    case = _CASES[step]

    outcomes = await _run(case, _service(case, lambda *_a, **_k: case.ok_result))

    assert [o.name for o in outcomes] == ["success"]
    assert set(outcomes[0].context.devices) == {"a", "b"}


@pytest.mark.asyncio
@pytest.mark.parametrize("step", list(_CASES))
async def test_connection_loss_aborts_and_keeps_the_devices_already_done(step: str) -> None:
    case = _CASES[step]
    service = _service(case, _fails_nth_device(case, SecretManagerError("down"), nth=2))

    outcomes = await _run(case, service)

    by_name = {o.name: o.context.devices for o in outcomes}
    assert set(by_name["success"]) == {"a"}  # done before the loss: keeps its result
    assert set(by_name["failure"]) == {"b"}  # not reached: fails with the transport cause
    assert by_name["failure"]["b"].status == DeviceStatus.FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize("step", list(_CASES))
async def test_an_unexpected_error_fails_only_that_device(step: str) -> None:
    case = _CASES[step]
    service = _service(case, _fails_nth_device(case, RuntimeError("vault exploded")))

    outcomes = await _run(case, service)

    by_name = {o.name: o.context.devices for o in outcomes}
    assert set(by_name["success"]) == {"b"}
    assert set(by_name["failure"]) == {"a"}
    assert by_name["failure"]["a"].status == DeviceStatus.FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize("step", list(_CASES))
async def test_an_unexpected_error_text_is_not_stored(step: str) -> None:
    case = _CASES[step]
    service = _service(case, _fails_nth_device(case, RuntimeError(f"token={_SECRET}")))

    try:
        outcomes = await _run(case, service)
    except RuntimeError as exc:
        pytest.fail(f"the step aborted with the exception text: {exc}")

    stored = "".join(
        e.message for o in outcomes for d in o.context.devices.values() for e in d.errors
    )
    assert _SECRET not in stored


@pytest.mark.asyncio
async def test_a_miss_records_a_failure_reason() -> None:
    case = _CASES["secret-get"]

    outcomes = await _run(case, _service(case, lambda *_a, **_k: None))

    error = {o.name: o for o in outcomes}["failure"].context.devices["a"].errors[-1]
    assert error.code == "secret_not_found"
    assert error.failure is not None and error.failure.kind == "not_found"


@pytest.mark.asyncio
async def test_an_unusable_source_records_a_failure_reason() -> None:
    case = _CASES["secret-set"]
    config = {**case.config, "source_path": "run_input.missing"}
    case = _Case(case.module, case.method, config, case.ok_result, run_input=True)

    outcomes = await _run(case, _service(case, lambda *_a, **_k: None))

    error = {o.name: o for o in outcomes}["failure"].context.devices["a"].errors[-1]
    assert error.code == "source_unresolved"
    assert error.failure is not None and error.failure.kind == "bad_request"


@pytest.mark.asyncio
@pytest.mark.parametrize("step", list(_CASES))
async def test_a_value_error_from_the_service_fails_that_device_with_its_text(step: str) -> None:
    case = _CASES[step]
    service = _service(case, _fails_nth_device(case, ValueError("field is not allowed")))

    outcomes = await _run(case, service)

    by_name = {o.name: o.context.devices for o in outcomes}
    assert set(by_name["success"]) == {"b"}
    assert by_name["failure"]["a"].errors[-1].message == "field is not allowed"


@pytest.mark.asyncio
@pytest.mark.parametrize("step", list(_CASES))
async def test_cancellation_is_not_turned_into_a_device_failure(step: str) -> None:
    import asyncio

    case = _CASES[step]
    service = _service(case, _fails_nth_device(case, asyncio.CancelledError()))

    with pytest.raises(asyncio.CancelledError):
        await _run(case, service)


_COUNT_KEYS = {
    "secret-get": ({"found_count": 1, "missing_count": 1}, "found 1, missing 1"),
    "secret-set": ({"written_count": 1, "failed_count": 1}, "written 1, failed 1"),
    "secret-generate": ({"generated_count": 1}, "generated 1, failed 1"),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("step", list(_CASES))
async def test_counts_and_summary_keep_their_names(step: str) -> None:
    case = _CASES[step]
    service = _service(case, _fails_nth_device(case, ValueError("no")))
    keys, summary = _COUNT_KEYS[step]

    outcomes = await _run(case, service)

    by = {o.name: o for o in outcomes}
    metadata = by["success"].context.metadata
    for key, value in keys.items():
        assert metadata[f"node-1.{key}"] == value
    assert ("node-1.failed_count" in metadata) == ("failed_count" in keys)
    assert by["success"].summary == summary
