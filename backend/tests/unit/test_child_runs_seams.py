"""``services.execution.child_runs``: input validation without starting, and the 503 translation."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from core.domain_exceptions import ValidationFailedError
from services.execution import child_runs
from services.execution.child_runs import CallingRunMissingError
from services.execution.dispatch_breaker import EngineUnavailableError
from services.execution.run_input_validation import RunInputValidationError


def _patched(*, parent=MagicMock(), service=None, resolve=None):
    run_service = service or MagicMock()
    repo = MagicMock()
    repo.return_value.get_run.return_value = parent
    return (
        patch("core.database.SessionLocal", MagicMock()),
        patch("repositories.run_repository.RunRepository", repo),
        patch("services.execution.run_service.RunService", run_service),
        patch(
            "services.execution.run_input_validation.resolve_run_inputs",
            resolve or MagicMock(),
        ),
    )


def _run(patches, fn, *args):
    with patches[0], patches[1], patches[2], patches[3]:
        return fn(*args)


def test_start_child_turns_a_503_into_engine_unavailable() -> None:
    service = MagicMock()
    service.return_value.start_child_run.side_effect = HTTPException(status_code=503)
    with pytest.raises(EngineUnavailableError):
        _run(_patched(service=service), child_runs.start_child, 1, 7, {})


def test_start_child_leaves_other_http_errors_alone() -> None:
    service = MagicMock()
    service.return_value.start_child_run.side_effect = HTTPException(status_code=500)
    with pytest.raises(HTTPException) as info:
        _run(_patched(service=service), child_runs.start_child, 1, 7, {})
    assert info.value.status_code == 500


def test_start_child_returns_the_new_run_id() -> None:
    service = MagicMock()
    service.return_value.start_child_run.return_value.id = 42
    assert _run(_patched(service=service), child_runs.start_child, 1, 7, {}) == 42


def test_validate_child_inputs_resolves_every_run_against_the_workflow() -> None:
    service = MagicMock()
    service.return_value.require_child_target.return_value.static_attributes = ["attrs"]
    resolve = MagicMock()
    _run(
        _patched(service=service, resolve=resolve),
        child_runs.validate_child_inputs,
        1,
        7,
        [{"a": 1}, {"a": 2}],
    )
    assert [c.args for c in resolve.call_args_list] == [
        (["attrs"], {"a": 1}),
        (["attrs"], {"a": 2}),
    ]
    service.return_value.start_child_run.assert_not_called()


def test_validate_child_inputs_names_the_wrong_input() -> None:
    resolve = MagicMock(side_effect=[None, RunInputValidationError("input 'x' is required")])
    with pytest.raises(ValidationFailedError, match="input 'x' is required"):
        _run(_patched(resolve=resolve), child_runs.validate_child_inputs, 1, 7, [{}, {}])


def test_validate_child_inputs_needs_the_calling_run() -> None:
    with pytest.raises(CallingRunMissingError):
        _run(_patched(parent=None), child_runs.validate_child_inputs, 1, 7, [{}])
