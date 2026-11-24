"""W7-01 (P-E): Batfish errors carry a closed-vocabulary ``FailureInfo``.

Before, no Batfish error had one, so a stopped coordinator and a bad snapshot were both recorded
as ``internal_error`` and the runner withheld the sentence. The classification never copies the
message; its inputs are the exception class and the transport cause chain.
"""

from __future__ import annotations

import pytest

from models.failure import failure_for_step_exception, failure_from_exception
from services.batfish.common.exceptions import (
    BatfishAnswerFailedError,
    BatfishAPIError,
    BatfishError,
    BatfishValidationError,
)
from services.execution.step_runner.signals import classify_step_exception

_SECRET = "coordinator said: password hunter2 at 10.9.9.9"


def _api_error(cause: BaseException | None) -> BatfishAPIError:
    error = BatfishAPIError(_SECRET)
    error.__cause__ = cause
    return error


@pytest.mark.parametrize(
    ("error", "kind", "retryable"),
    [
        (BatfishValidationError(_SECRET), "bad_request", False),
        (BatfishAnswerFailedError("q", {"x": 1}), "bad_request", False),
        (_api_error(TimeoutError()), "timeout", True),
        (_api_error(ConnectionRefusedError()), "refused", False),
        (_api_error(RuntimeError("opaque")), "server_error", True),
        (_api_error(None), "server_error", True),
    ],
)
def test_classification(error: BatfishError, kind: str, retryable: bool) -> None:
    failure = error.failure
    assert failure.kind == kind
    assert failure.retryable is retryable
    assert failure.exception_type == type(error).__name__
    assert failure.phase == "api"
    assert failure.hint is not None
    assert "hunter2" not in repr(failure)


def test_a_requests_style_timeout_in_the_chain_is_a_timeout() -> None:
    class ReadTimeout(Exception):  # the class name is what the classifier looks at
        pass

    assert _api_error(ReadTimeout()).failure.kind == "timeout"


def test_the_runner_finds_the_failure_through_a_wrapping_step_error() -> None:
    wrapped = RuntimeError("step failed")
    wrapped.__cause__ = _api_error(TimeoutError())
    assert failure_from_exception(wrapped) is not None
    assert failure_for_step_exception(wrapped, category="execution").kind == "timeout"


def test_a_batfish_error_is_no_longer_an_unexplained_internal_error() -> None:
    error = _api_error(TimeoutError())
    category, message = classify_step_exception(error)
    assert category == "internal"  # the sentence stays withheld ...
    assert failure_for_step_exception(error, category=category).kind == "timeout"  # ... the kind
