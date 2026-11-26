"""Bounds on step inputs that today are unbounded or read as something else (P-T write-first).

``reachable`` (W3b-04) and the ``get-from-user`` inventory reference (W10-04). Tests marked
``strict_xfail`` fail on today's code; the plain ones pin what must keep working.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit._step_helpers import make_run
from workflow_steps.get_from_user import executor as inv
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

_EXEC = "workflow_steps.get_from_user.executor"


def _service(**kwargs: Any) -> MagicMock:
    service = MagicMock()
    service.resolve_saved_inventory_devices_by_id = AsyncMock(**kwargs)
    return service


@pytest.mark.asyncio
@pytest.mark.parametrize("reference", ["abc", "", None])
async def test_inventory_reference_must_be_an_inventory_id(reference: Any) -> None:
    with pytest.raises(ValueError, match="inventory id"):
        await inv._inventory_device_text(MagicMock(), make_run(), {}, reference)


@pytest.mark.asyncio
async def test_inventory_is_read_as_the_triggering_user() -> None:
    service = _service(return_value=[])
    with (
        patch(f"{_EXEC}.default_nautobot_source_id", return_value="src"),
        patch(f"{_EXEC}.resolve_nautobot_credentials", return_value=MagicMock()),
        patch.object(inv.service_factory, "build_nautobot_source_service", return_value=service),
        patch(f"{_EXEC}.acting_username", return_value="alice") as acting,
    ):
        await inv._inventory_device_text(MagicMock(), make_run(triggered_by_id=5), {}, "12")

    acting.assert_called_once()
    assert acting.call_args.args[1] == 5
    service.resolve_saved_inventory_devices_by_id.assert_awaited_once_with(12, "alice")


@pytest.mark.asyncio
async def test_a_permission_error_becomes_a_config_error() -> None:
    service = _service(side_effect=PermissionError("no"))
    with (
        patch(f"{_EXEC}.default_nautobot_source_id", return_value="src"),
        patch(f"{_EXEC}.resolve_nautobot_credentials", return_value=MagicMock()),
        patch.object(inv.service_factory, "build_nautobot_source_service", return_value=service),
        patch(f"{_EXEC}.acting_username", return_value="alice"),
        pytest.raises(ValueError, match="not accessible to the user that triggered this run"),
    ):
        await inv._inventory_device_text(MagicMock(), make_run(triggered_by_id=5), {}, "12")


@pytest.mark.asyncio
@pytest.mark.parametrize("triggered_by_id", [None, 99])  # no user, or a user that is gone
async def test_a_run_without_a_user_reads_as_nobody(triggered_by_id: int | None) -> None:
    """W10-04, maintainer decision 2026-11-27: read with no username, so the service lets only
    a global inventory through; a private one is reported as not accessible."""
    service = _service(side_effect=PermissionError("private"))
    with (
        patch(f"{_EXEC}.default_nautobot_source_id", return_value="src"),
        patch(f"{_EXEC}.resolve_nautobot_credentials", return_value=MagicMock()),
        patch.object(inv.service_factory, "build_nautobot_source_service", return_value=service),
        patch(f"{_EXEC}.acting_username", return_value=None),
        pytest.raises(ValueError, match="global inventories only"),
    ):
        await inv._inventory_device_text(
            MagicMock(), make_run(triggered_by_id=triggered_by_id), {}, "12"
        )

    service.resolve_saved_inventory_devices_by_id.assert_awaited_once_with(12, None)


@pytest.mark.asyncio
async def test_without_any_nautobot_source_the_reference_is_a_config_error() -> None:
    with (
        patch(f"{_EXEC}.default_nautobot_source_id", return_value=None),
        pytest.raises(ValueError, match="no Nautobot source is configured"),
    ):
        await inv._inventory_device_text(MagicMock(), make_run(), {}, "12")
