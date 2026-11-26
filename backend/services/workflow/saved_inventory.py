"""Reading a saved inventory for a workflow run (W10-12).

Shared by the ``get-from-user`` (Get from User) and ``get-nautobot-devices`` (Get Devices from
Nautobot) steps and the run-start check of a reference input (``services/execution/
reference_resolver.py``). A run reads a saved inventory as the user that triggered it; a run
without a triggering user (a webhook-approved change request) reads global inventories only
(``InventoryService.get_inventory_as``, W10-04).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from core.models.workflows import Workflow
from repositories.user_repository import UserRepository
from services.settings.settings_service import SettingsService
from services.workflow.device_lines import device_line

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from services.sources.nautobot.source_service import NautobotSourceService


def acting_username(db: Session, user_id: int | None) -> str | None:
    """Username of the user that triggered a run; ``None`` when there is none (or it is gone)."""
    if user_id is None:
        return None
    user = UserRepository(db).get_by_id(user_id)
    return user.username if user else None


def is_inventory_reference(db: Session, workflow_id: int, param_name: str) -> bool:
    """True when ``param_name`` is declared as an inventory reference on the workflow."""
    workflow = db.get(Workflow, workflow_id)
    for attr in (workflow.static_attributes if workflow else None) or []:
        if (
            isinstance(attr, dict)
            and attr.get("name") == param_name
            and attr.get("type") == "reference"
            and attr.get("ref_kind") == "inventory"
        ):
            return True
    return False


def default_nautobot_source_id(db: Session) -> str | None:
    """The first configured Nautobot source, or ``None`` when there is none."""
    sources = SettingsService(db).list_nautobot_source_summaries().sources
    return sources[0].source_id if sources else None


async def inventory_device_lines(
    service: NautobotSourceService, inventory_id: int, username: str | None
) -> list[str]:
    """One ``name,ip[,driver]`` line per device of the saved inventory, read as ``username``.

    Raises what ``resolve_saved_inventory_devices_by_id`` raises: ``PermissionError`` for an
    inventory the run may not read, ``ValueError`` for a missing or inactive one.
    """
    devices: list[Any] = await service.resolve_saved_inventory_devices_by_id(inventory_id, username)
    return [
        line
        for device in devices
        if (
            line := device_line(
                name=device.name,
                ip=device.primary_ip4,
                network_driver=device.platform_network_driver,
                platform=device.platform,
            )
        )
    ]
