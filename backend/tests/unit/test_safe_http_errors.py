"""client_error_message: what a 4xx may say about a caught exception."""

from __future__ import annotations

import pytest
from pydantic import BaseModel, Field, ValidationError

from core.safe_http_errors import client_error_message


class _Probe(BaseModel):
    tenant: str = Field(min_length=36)
    port: int


def _validation_error() -> ValidationError:
    with pytest.raises(ValidationError) as caught:
        _Probe(tenant="pwtest", port="eighty")  # type: ignore[arg-type]
    return caught.value


def test_plain_value_error_keeps_its_own_message() -> None:
    assert client_error_message(ValueError("Unknown platform 'x'")) == "Unknown platform 'x'"


def test_validation_error_names_fields_and_rules_only() -> None:
    message = client_error_message(_validation_error())
    assert "tenant: String should have at least 36 characters" in message
    assert "port:" in message
    for leak in ("pwtest", "eighty", "input_value", "pydantic", "_Probe", "validation error for"):
        assert leak not in message


def test_os_error_with_errno_hides_the_path() -> None:
    message = client_error_message(
        FileNotFoundError(2, "No such file or directory", "/srv/data/x.crt")
    )
    assert "/srv" not in message
    assert "x.crt" not in message
    assert message == "The file operation failed"


def test_os_error_raised_with_a_message_keeps_it() -> None:
    assert client_error_message(FileNotFoundError("Certificate not found: a.crt")) == (
        "Certificate not found: a.crt"
    )


def test_empty_message_falls_back() -> None:
    assert client_error_message(ValueError(), fallback="Invalid request") == "Invalid request"
    assert client_error_message(ValueError("  ")) == "The request could not be processed"


def test_os_error_with_a_filename_hides_it_even_without_an_errno() -> None:
    message = client_error_message(FileNotFoundError(None, "missing", "/srv/secret.crt"))
    assert "/srv" not in message
    assert "secret.crt" not in message
    assert message == "The file operation failed"


def test_os_error_with_a_second_filename_hides_it() -> None:
    error = OSError(None, "rename failed", "/srv/a.crt", None, "/srv/b.crt")
    assert "/srv" not in client_error_message(error)
