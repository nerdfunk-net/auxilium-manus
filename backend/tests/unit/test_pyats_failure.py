"""pyATS shim errors classify into the closed failure vocabulary without copying text."""

from __future__ import annotations

import pytest

from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from services.pyats.common.failure import classify_pyats_exception


@pytest.mark.parametrize(
    ("exc", "kind", "retryable"),
    [
        (PyATSAPIError("x", code="timeout"), "timeout", True),
        (PyATSAPIError("x", http_status=401), "auth_failed", False),
        (PyATSAPIError("x", http_status=403), "permission_denied", False),
        (PyATSAPIError("x", http_status=429), "rate_limited", True),
        (PyATSAPIError("x", http_status=503), "server_error", True),
        (PyATSAPIError("x", http_status=404), "bad_request", False),
        (PyATSValidationError("x"), "bad_request", False),
        (PyATSAPIError("x", code="transport"), "unknown", False),
    ],
)
def test_kind(exc: PyATSAPIError, kind: str, retryable: bool) -> None:
    info = classify_pyats_exception(exc)
    assert info.kind == kind
    assert info.retryable is retryable
    assert info.exception_type == type(exc).__name__


def test_transport_cause_is_classified() -> None:
    try:
        try:
            raise ConnectionRefusedError("Connection refused")
        except ConnectionRefusedError as cause:
            raise PyATSAPIError("pyATS shim job request failed", code="transport") from cause
    except PyATSAPIError as exc:
        assert exc.failure.kind == "refused"


def test_message_text_is_never_copied() -> None:
    info = classify_pyats_exception(PyATSAPIError("token=abc123 password=hunter2", http_status=500))
    assert "hunter2" not in info.model_dump_json()
