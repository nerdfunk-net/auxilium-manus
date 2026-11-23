"""store-in-db: a database error on one device must not poison the next (P-T write-first, W9-04).

The session is shared by the whole loop. After a failed flush SQLAlchemy refuses further work on
it (``PendingRollbackError``) until it is rolled back, so every later device would fail too.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models.base import Base
from core.models.device_data_records import DeviceDataRecord
from models.workflow_context import DeviceStatus
from services.device_data.device_data_service import DeviceDataService
from tests.unit._step_helpers import call_step, make_context, make_device, make_run, strict_xfail
from workflow_steps.store_in_db.executor import execute

_ORIGINAL = DeviceDataService.store_device_data


@pytest.fixture
def sessions():  # noqa: ANN201
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine, tables=[DeviceDataRecord.__table__])
    factory = sessionmaker(bind=engine)
    with patch("workflow_steps.store_in_db.executor.get_db_session", side_effect=factory):
        yield factory
    engine.dispose()


def _failing_flush_for(name: str):  # noqa: ANN202
    """``store_device_data`` that breaks the session with a real failed flush for ``name``."""

    def store(self, *, device_name, storage_key, data):  # noqa: ANN001, ANN202
        if device_name == name:
            self.repository.db.add(DeviceDataRecord(device_name=None, storage_key="k", data={}))
            self.repository.db.flush()  # NOT NULL violation: IntegrityError, session unusable
        return _ORIGINAL(self, device_name=device_name, storage_key=storage_key, data=data)

    return store


async def _run(*names: str):  # noqa: ANN202
    bags = {"x": {"v": 1}}
    devices = [make_device(n, name=n, attribute_bags=bags) for n in names]
    return await call_step(
        execute,
        {"storage_key": "k", "content_source": "attribute_bags"},
        make_context(devices),
        run=make_run(),
    )


@pytest.mark.asyncio
async def test_a_failed_flush_fails_that_device(sessions) -> None:  # noqa: ANN001
    with patch.object(DeviceDataService, "store_device_data", _failing_flush_for("bad")):
        outcomes = await _run("bad")

    failed = next(o for o in outcomes if o.name == "failure").context.devices["bad"]
    assert failed.status == DeviceStatus.FAILED


@strict_xfail("W9-04", "no rollback: the failed flush leaves the shared session unusable")
@pytest.mark.asyncio
async def test_the_next_device_is_stored_after_a_failed_flush(sessions) -> None:  # noqa: ANN001
    with patch.object(DeviceDataService, "store_device_data", _failing_flush_for("bad")):
        outcomes = await _run("bad", "good")

    by_name = {o.name: o.context.devices for o in outcomes}
    assert set(by_name["success"]) == {"good"}
    assert set(by_name["failure"]) == {"bad"}
    with sessions() as db:
        assert [r.device_name for r in db.scalars(select(DeviceDataRecord))] == ["good"]


@strict_xfail("W9-04", "the stored error carries the SQL statement and its parameters")
@pytest.mark.asyncio
async def test_the_stored_error_has_no_sql(sessions) -> None:  # noqa: ANN001
    with patch.object(DeviceDataService, "store_device_data", _failing_flush_for("bad")):
        outcomes = await _run("bad")

    failed = next(o for o in outcomes if o.name == "failure").context.devices["bad"]
    message = " ".join(e.message for e in failed.errors)
    assert "INSERT" not in message
    assert "device_data_records" not in message
