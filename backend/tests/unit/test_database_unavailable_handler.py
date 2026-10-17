"""O2-06: a database outage is a JSON 503 with an error id, not a bare plain-text 500."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

import main


def _call(exc: Exception):
    return asyncio.run(main.database_unavailable_handler(MagicMock(), exc))


@pytest.mark.parametrize(
    "exc",
    [
        OperationalError("SELECT 1", {}, Exception("connection refused")),
        PoolTimeoutError("QueuePool limit of size 10 overflow 10 reached"),
    ],
)
def test_database_outage_is_a_503_with_retry_after(exc: Exception) -> None:
    response = _call(exc)

    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    detail = json.loads(response.body)["detail"]
    assert "database" in detail["message"].lower()
    assert detail["error_id"]


def test_no_driver_text_reaches_the_client() -> None:
    response = _call(
        OperationalError("SELECT secret", {"p": "x"}, Exception("password authentication failed"))
    )

    body = response.body.decode()
    assert "password authentication" not in body
    assert "SELECT secret" not in body


def test_the_handlers_are_registered_for_both_exception_types() -> None:
    registered = main.app.exception_handlers
    assert registered[OperationalError] is main.database_unavailable_handler
    assert registered[PoolTimeoutError] is main.database_unavailable_handler
