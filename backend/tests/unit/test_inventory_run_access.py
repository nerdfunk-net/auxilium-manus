"""A saved inventory read for a run follows the run user's access; without a user, global only.

W10-04 was fixed only in get-from-user (Get from User), which refused every inventory when the run
had no triggering user. ``PersistenceService.get_inventory(id, username=None)`` skips the access
check, so get-nautobot-devices (Get Devices from Nautobot) and the run-start check of a reference
input (``reference_resolver``) read another user's *private* inventory for a run without a user
(a webhook-approved change-request deploy). Maintainer decision (2026-11-27): without a triggering
user only a global inventory resolves, in all three places.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import Table, create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.models.inventories import Inventory
from models.sources_nautobot import DeviceInfo
from models.workflow_context import WorkflowContext
from repositories.inventory_repository import InventoryRepository
from services.execution.reference_resolver import (
    ReferenceValidationError,
    validate_reference_inputs,
)
from services.nautobot.credentials import NautobotCredentials
from services.sources.nautobot.persistence_service import InventoryService
from services.sources.nautobot.source_service import NautobotSourceService
from workflow_steps.get_from_user import executor as get_from_user

pytestmark = pytest.mark.asyncio

_CREDS = NautobotCredentials(url="http://nb.test", token="tok")


@pytest.fixture
def db() -> Any:
    engine = create_engine("sqlite:///:memory:")
    cast(Table, Inventory.__table__).create(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def _inventory(db: Session, *, scope: str, owner: str = "bob") -> int:
    inventory_id = InventoryService(InventoryRepository(db)).create_inventory(
        {
            "name": f"{scope}-{owner}",
            "created_by": owner,
            "scope": scope,
            "inventory_type": "static",
            "device_ids": ["d1"],
        }
    )
    assert inventory_id is not None
    return inventory_id


def _source_service(db: Session) -> NautobotSourceService:
    service = NautobotSourceService(
        MagicMock(), _CREDS, persistence_service=InventoryService(InventoryRepository(db))
    )
    service.query_service = MagicMock()
    service.query_service._query_all_devices = AsyncMock(
        return_value=[DeviceInfo(id="d1", name="r1", primary_ip4="10.0.0.1/24")]
    )
    return service


# -- the device read of both steps ------------------------------------------------------------


async def test_without_a_user_a_private_inventory_is_refused(db: Session) -> None:
    private = _inventory(db, scope="private")
    with pytest.raises(PermissionError):
        await _source_service(db).resolve_saved_inventory_devices_by_id(private, None)


async def test_without_a_user_a_global_inventory_resolves(db: Session) -> None:
    shared = _inventory(db, scope="global")
    devices = await _source_service(db).resolve_saved_inventory_devices_by_id(shared, None)
    assert [d.name for d in devices] == ["r1"]


async def test_a_user_keeps_the_existing_rule(db: Session) -> None:
    private = _inventory(db, scope="private", owner="bob")
    service = _source_service(db)
    assert [d.name for d in await service.resolve_saved_inventory_devices_by_id(private, "bob")]
    with pytest.raises(PermissionError):
        await service.resolve_saved_inventory_devices_by_id(private, "alice")


# -- the run-start check of a reference input ------------------------------------------------

_ATTRS = [{"name": "inv", "type": "reference", "ref_kind": "inventory"}]


async def test_run_start_without_a_user_refuses_a_private_inventory(db: Session) -> None:
    private = _inventory(db, scope="private")
    with pytest.raises(ReferenceValidationError) as info:
        validate_reference_inputs(_ATTRS, {"inv": private}, db=db, acting_user_id=None)
    cause = info.value.__cause__
    assert isinstance(cause, ReferenceValidationError)
    assert cause.code == "not_accessible"


async def test_run_start_without_a_user_accepts_a_global_inventory(db: Session) -> None:
    shared = _inventory(db, scope="global")
    validate_reference_inputs(_ATTRS, {"inv": shared}, db=db, acting_user_id=None)


# -- get-from-user (Get from User) -------------------------------------------------------------


async def _run_get_from_user(read: AsyncMock) -> Any:
    run = MagicMock(id=1, workflow_id=3, run_inputs={"target": "4"}, triggered_by_id=None)
    run_db = MagicMock()
    run_db.get.return_value = MagicMock(static_attributes=_ATTRS_TARGET)
    source = MagicMock()
    source.resolve_saved_inventory_devices_by_id = read
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=run_db),
        patch(
            "services.settings.settings_service.SettingsService.get_source_config_for_step",
            return_value={"url": "http://nb.test", "token": "tok"},
        ),
        patch("service_factory.build_nautobot_source_service", return_value=source),
    ):
        return await get_from_user.execute(
            config={"device_param": "target", "nautobot_source_id": "src"},
            context=WorkflowContext(run_id="1", workflow_id="3"),
            run=run,
            artifact_service=MagicMock(),
            node_id="n1",
            device_sessions=MagicMock(),
        )


_ATTRS_TARGET = [{"name": "target", "type": "reference", "ref_kind": "inventory"}]


async def test_get_from_user_without_a_user_reads_a_global_inventory() -> None:
    read = AsyncMock(return_value=[DeviceInfo(id="d1", name="r1", primary_ip4="10.0.0.1/24")])
    outcomes = await _run_get_from_user(read)

    read.assert_awaited_once_with(4, None)
    assert [d.name for d in outcomes[0].context.devices.values()] == ["r1"]


async def test_get_from_user_without_a_user_reports_a_private_inventory() -> None:
    read = AsyncMock(side_effect=PermissionError("Access denied to inventory 4"))
    with pytest.raises(ValueError, match="inventory 4 is not accessible"):
        await _run_get_from_user(read)


async def test_a_missing_inventory_is_none_for_any_caller(db: Session) -> None:
    service = InventoryService(InventoryRepository(db))
    assert service.get_inventory_as(404, None) is None
    assert service.get_inventory_as(404, "alice") is None
