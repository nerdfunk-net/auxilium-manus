"""secret-get / secret-set / secret-generate: what one device's failure does to the others.

P-T write-first for the per-device runner (D1, W10-09): a failure that is not a
``SecretManagerError`` is a failure of that device. Today it aborts the whole step with a
``RuntimeError`` that carries the exception text. The ``strict_xfail`` tests become plain tests
when the runner lands; the others pin what must not change (connection loss aborts the step
and keeps the devices already done).
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
    strict_xfail,
)
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
    module = case.module.__name__
    with (
        patch_object_session(module),
        patch.object(case.module, "SecretManagerService", return_value=service),
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


@strict_xfail("W10-09", "an unexpected exception aborts the step instead of failing one device")
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


@strict_xfail("W10-09", "the RuntimeError text (the vault error) reaches the stored run")
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
