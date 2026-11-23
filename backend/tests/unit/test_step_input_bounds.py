"""Bounds on step inputs that today are unbounded or read as something else (P-T write-first).

``reachable`` (W3b-04) and the ``get-from-user`` inventory reference (W10-04). Tests marked
``strict_xfail`` fail on today's code; the plain ones pin what must keep working.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit._step_helpers import make_run, strict_xfail
from workflow_steps.get_from_user import inventory_reference as inv
from workflow_steps.reachable.executor import _parse_positive_int, _parse_positive_number

# ── reachable ──────────────────────────────────────────────────────────────────────────────────


def test_reachable_defaults_and_ordinary_values_parse() -> None:
    assert _parse_positive_int({}, "ping_count") >= 1
    assert _parse_positive_int({"ping_count": "3"}, "ping_count") == 3
    assert _parse_positive_number({"timeout_seconds": "2.5"}, "timeout_seconds") == 2.5


@pytest.mark.parametrize("raw", [0, -1, "abc"])
def test_reachable_refuses_non_positive_and_non_numeric_counts(raw: Any) -> None:
    with pytest.raises(ValueError):
        _parse_positive_int({"ping_count": raw}, "ping_count")


@pytest.mark.parametrize("raw", [None, ""])
def test_reachable_blank_count_means_the_default(raw: Any) -> None:
    assert _parse_positive_int({"ping_count": raw}, "ping_count") >= 1


@pytest.mark.parametrize("raw", [0, -0.5, "abc"])
def test_reachable_refuses_non_positive_and_non_numeric_timeouts(raw: Any) -> None:
    with pytest.raises(ValueError):
        _parse_positive_number({"timeout_seconds": raw}, "timeout_seconds")


@pytest.mark.parametrize("raw", ["nan", "inf", float("nan"), float("inf")])
def test_reachable_refuses_nan_and_infinite_timeouts(raw: Any) -> None:
    with pytest.raises(ValueError):
        _parse_positive_number({"timeout_seconds": raw}, "timeout_seconds")


def test_reachable_refuses_a_boolean_count() -> None:
    with pytest.raises(ValueError):
        _parse_positive_int({"ping_count": True}, "ping_count")


def test_reachable_caps_the_ping_count_at_twenty() -> None:
    with pytest.raises(ValueError):
        _parse_positive_int({"ping_count": 1_000_000}, "ping_count")


def test_reachable_caps_the_timeout_at_sixty_seconds() -> None:
    with pytest.raises(ValueError):
        _parse_positive_number({"timeout_seconds": 86_400}, "timeout_seconds")


# ── get-from-user: inventory reference ─────────────────────────────────────────────────────────


def _patched(*, service: MagicMock) -> Any:
    return (
        patch.object(inv, "object_session", return_value=MagicMock(name="db")),
        patch.object(inv, "_pick_source_id", return_value="src"),
        patch.object(inv, "resolve_nautobot_credentials", return_value=MagicMock()),
        patch.object(inv.service_factory, "build_nautobot_source_service", return_value=service),
    )


@pytest.mark.asyncio
async def test_inventory_reference_without_a_db_session_is_a_runtime_error() -> None:
    with patch.object(inv, "object_session", return_value=None):
        with pytest.raises(RuntimeError, match="no active DB session"):
            await inv.inventory_device_text(make_run(), {}, "1")


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["abc", "", None])
async def test_inventory_reference_must_be_an_inventory_id(reference: Any) -> None:
    with patch.object(inv, "object_session", return_value=MagicMock()):
        with pytest.raises(ValueError, match="inventory id"):
            await inv.inventory_device_text(make_run(), {}, reference)


@pytest.mark.asyncio
async def test_inventory_is_read_as_the_triggering_user() -> None:
    service = MagicMock()
    service.resolve_saved_inventory_devices_by_id = AsyncMock(return_value=[])
    user = MagicMock()
    user.username = "alice"
    patches = _patched(service=service)
    with (
        patches[0],
        patches[1],
        patches[2],
        patches[3],
        patch.object(inv, "UserRepository") as repo,
    ):
        repo.return_value.get_by_id.return_value = user
        await inv.inventory_device_text(make_run(triggered_by_id=5), {}, "12")

    service.resolve_saved_inventory_devices_by_id.assert_awaited_once_with(12, "alice")


@pytest.mark.asyncio
async def test_a_permission_error_becomes_a_config_error() -> None:
    service = MagicMock()
    service.resolve_saved_inventory_devices_by_id = AsyncMock(side_effect=PermissionError("no"))
    patches = _patched(service=service)
    with patches[0], patches[1], patches[2], patches[3], patch.object(inv, "UserRepository"):
        with pytest.raises(ValueError, match="not accessible"):
            await inv.inventory_device_text(make_run(triggered_by_id=5), {}, "12")


@strict_xfail("W10-04", "no triggering user: the inventory is read without any permission check")
@pytest.mark.asyncio
async def test_a_run_without_a_triggering_user_reads_no_inventory() -> None:
    service = MagicMock()
    service.resolve_saved_inventory_devices_by_id = AsyncMock(return_value=[])
    patches = _patched(service=service)
    with patches[0], patches[1], patches[2], patches[3], patch.object(inv, "UserRepository"):
        try:
            await inv.inventory_device_text(make_run(triggered_by_id=None), {}, "12")
        except Exception:  # noqa: BLE001, S110  # a refusal of any type is fine, reading is not
            pass

    service.resolve_saved_inventory_devices_by_id.assert_not_awaited()
