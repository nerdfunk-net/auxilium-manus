"""What collect-client-data and get-catalyst-center-client-data share around the store (W8-04)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError

from core.config import settings
from models.client_data import ClientCollectionStatus, TooManyRowsError
from models.workflow_context import Capability, DeviceContext, DeviceStatus
from workflow_steps.common.client_data_store import (
    StorageRejected,
    duplicate_failure,
    ip_or_none,
    storage_failure,
    store_collection,
    store_collection_sync,
    too_many_rows_failure,
    with_summary,
)
from workflow_steps.common.duplicate_keys import DUPLICATE_KEY_CODE, DUPLICATE_KEY_FAILURE

_MOD = "workflow_steps.common.client_data_store"
_AT = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _device() -> DeviceContext:
    return DeviceContext(id="d1", name="core1", hostname="core1")


def _collection(**overrides: object) -> dict:
    return {
        "session_id": "run-1",
        "device_name": "core1",
        "device_ip": "10.0.0.1",
        "ip_rows": ("ip",),
        "mac_rows": ("mac",),
        "hostname_rows": ("host",),
        "status": ClientCollectionStatus(arp_status="ok", mac_status="ok"),
        "neighbor_rows": ("nbr",),
        "collected_at": _AT,
        "target_host": "10.0.0.1",
        **overrides,
    }


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("10.0.0.1", "10.0.0.1"),
        ("2001:db8::1", "2001:db8::1"),
        ("core1", None),
        ("", None),
        (None, None),
    ],
)
def test_ip_or_none_stores_only_an_address(host: str | None, expected: str | None) -> None:
    assert ip_or_none(host) == expected


def test_store_forwards_every_field_and_the_keep_setting_and_closes_the_session() -> None:
    db = MagicMock()
    with (
        patch(f"{_MOD}.get_db_session", return_value=db),
        patch(f"{_MOD}.ClientDataService") as svc,
    ):
        store_collection_sync(**_collection())

    svc.assert_called_once_with(db)
    svc.return_value.store_device_collection.assert_called_once_with(
        session_id="run-1",
        device_name="core1",
        device_ip="10.0.0.1",
        ip_rows=("ip",),
        mac_rows=("mac",),
        hostname_rows=("host",),
        status=ClientCollectionStatus(arp_status="ok", mac_status="ok"),
        neighbor_rows=("nbr",),
        keep_sessions=settings.client_data_keep_sessions,
        collected_at=_AT,
        target_host="10.0.0.1",
    )
    db.close.assert_called_once_with()


def test_neighbors_default_to_none() -> None:
    kwargs = _collection()
    del kwargs["neighbor_rows"]
    with patch(f"{_MOD}.get_db_session"), patch(f"{_MOD}.ClientDataService") as svc:
        store_collection_sync(**kwargs)

    assert svc.return_value.store_device_collection.call_args.kwargs["neighbor_rows"] == ()


def test_a_value_error_of_the_service_is_a_rejection_with_the_class_name_only() -> None:
    db = MagicMock()
    with (
        patch(f"{_MOD}.get_db_session", return_value=db),
        patch(f"{_MOD}.ClientDataService") as svc,
    ):
        svc.return_value.store_device_collection.side_effect = ValueError("secret value")
        with pytest.raises(StorageRejected) as info:
            store_collection_sync(**_collection())

    assert str(info.value) == "ValueError"
    assert isinstance(info.value.__cause__, ValueError)
    db.close.assert_called_once_with()


def test_a_database_error_passes_through_and_the_session_is_closed() -> None:
    db = MagicMock()
    with (
        patch(f"{_MOD}.get_db_session", return_value=db),
        patch(f"{_MOD}.ClientDataService") as svc,
    ):
        svc.return_value.store_device_collection.side_effect = SQLAlchemyError("INSERT ...")
        with pytest.raises(SQLAlchemyError):
            store_collection_sync(**_collection())

    db.close.assert_called_once_with()


@pytest.mark.asyncio
async def test_one_write_at_a_time_under_the_lock() -> None:
    lock = asyncio.Lock()
    seen: list[bool] = []

    def record(**kwargs: object) -> None:
        seen.append(lock.locked() and kwargs["session_id"] == "run-1")

    with patch(f"{_MOD}.store_collection_sync", record):
        await store_collection(lock, **_collection())

    assert seen == [True]
    assert not lock.locked()


def test_with_summary_stamps_the_summary_status_and_capability() -> None:
    device = _device()

    result = with_summary(device, "node-1", {"arp_entries": 2})

    assert result.status == DeviceStatus.OK
    assert Capability.PARSED in result.capabilities
    assert result.parsed["node-1"]["client_data"] == {"arp_entries": 2}
    assert device.parsed == {} and device.status != DeviceStatus.FAILED


def test_duplicate_failure_names_the_device_and_the_step() -> None:
    result = duplicate_failure(_device(), "node-1", step_id="collect-client-data")

    error = result.errors[-1]
    assert result.status == DeviceStatus.FAILED
    assert (error.code, error.step_id, error.node_id) == (
        DUPLICATE_KEY_CODE,
        "collect-client-data",
        "node-1",
    )
    assert "'core1'" in error.message
    assert error.failure == DUPLICATE_KEY_FAILURE


def test_the_row_cap_failure_names_table_and_limit() -> None:
    code, message, failure = too_many_rows_failure(TooManyRowsError("ARP", 7))

    assert code == "too_many_rows"
    assert "The ARP table" in message and "(7)" in message
    assert (failure.phase, failure.kind) == ("command", "payload_too_large")


def test_the_storage_failure_keeps_only_the_class_name() -> None:
    code, message, failure = storage_failure(SQLAlchemyError("INSERT INTO t VALUES ('secret')"))

    assert code == "storage_failed"
    assert message == "The collected data could not be stored"
    assert "secret" not in repr(failure)
    assert (failure.phase, failure.kind, failure.exception_type) == (
        "internal",
        "internal_error",
        "SQLAlchemyError",
    )
