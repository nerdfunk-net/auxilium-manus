"""W5-05 (P-E, D3): the Nautobot write steps keep the text of a ``NautobotError``.

The Nautobot client sanitises its messages at the source (``NautobotError`` documents "never text
taken from a response", with one capped, cleaned REST 400), and that text is the only place the
operator reads *why* Nautobot refused a write ("name: this name is taken"). A step that reduces it
to the class name hides it; every other exception still shows only its class name.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from services.nautobot.common.exceptions import NautobotAPIError
from workflow_steps.update_nautobot_ip.lookups import write_error

STEPS_ROOT = Path(__file__).resolve().parents[2] / "workflow_steps"

# The Nautobot write family: every catch-all there passes ``keep_text``.
NAUTOBOT_WRITE_FILES = (
    "add_ip_to_nautobot/executor.py",
    "common/device_location_sync.py",
    "common/nautobot_object_update.py",
    "get_next_free_ip/executor.py",
    "remove_from_nautobot/executor.py",
    "update_nautobot_ip/interfaces_mode.py",
    "update_nautobot_ip/lookups.py",
)

_SECRET = "driver text with 10.9.9.9 and a token"


def _calls_without_keep_text(relative: str) -> list[int]:
    tree = ast.parse((STEPS_ROOT / relative).read_text())
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", getattr(node.func, "attr", ""))
        == "device_error_from_exception"
        and not any(kw.arg == "keep_text" for kw in node.keywords)
    ]


@pytest.mark.parametrize("relative", NAUTOBOT_WRITE_FILES)
def test_every_catch_all_of_a_nautobot_write_step_keeps_the_nautobot_text(relative: str) -> None:
    assert _calls_without_keep_text(relative) == []


def test_a_nautobot_400_keeps_the_reason_the_operator_needs() -> None:
    exc = NautobotAPIError(
        "REST request failed with status 400: name: this name is taken", http_status=400
    )

    error = write_error(exc, "n1")

    assert error.message == "REST request failed with status 400: name: this name is taken"
    assert error.failure is not None
    assert error.failure.kind == "bad_request"


def test_any_other_exception_still_shows_only_its_class_name() -> None:
    error = write_error(RuntimeError(_SECRET), "n1")

    assert error.message == "RuntimeError"
    assert _SECRET not in repr(error)
    assert error.failure is not None
    assert error.failure.kind == "internal_error"
