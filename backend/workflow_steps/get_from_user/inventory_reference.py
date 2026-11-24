"""Turn an inventory *reference* run input into the device lines Get from User parses.

A workflow may declare its device input as a ``type == "reference"`` /
``ref_kind == "inventory"`` static attribute. Its run-input value is then an inventory id
("1"), not device text. This module reads that inventory (as the triggering user) and
returns one ``name,ip[,driver]`` line per device, the same format the step already parses.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session, object_session

import service_factory
from core.models.runs import WorkflowRun
from core.models.workflows import Workflow
from repositories.user_repository import UserRepository
from services.settings.settings_service import SettingsService
from services.workflow.device_lines import device_line
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.run_logging import log_run_id

logger = logging.getLogger(__name__)

_STEP = "get-from-user"


def is_inventory_reference(db: Session, run: WorkflowRun, param_name: str) -> bool:
    """True when ``param_name`` is declared as an inventory reference on the run's workflow."""
    workflow = db.get(Workflow, run.workflow_id)
    for attr in (workflow.static_attributes if workflow else None) or []:
        if (
            isinstance(attr, dict)
            and attr.get("name") == param_name
            and attr.get("type") == "reference"
            and attr.get("ref_kind") == "inventory"
        ):
            return True
    return False


def _pick_source_id(db: Session, config: dict[str, Any]) -> str:
    """The step's own Nautobot source, else the first configured one."""
    configured = str(config.get("nautobot_source_id") or "").strip()
    if configured:
        return configured
    sources = SettingsService(db).list_nautobot_source_summaries().sources
    if not sources:
        raise ValueError(f"{_STEP}: no Nautobot source is configured to resolve the inventory")
    return sources[0].source_id


async def inventory_device_text(
    run: WorkflowRun, config: dict[str, Any], reference: Any
) -> str:
    """Device lines for the inventory whose id is ``reference``."""
    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP}: WorkflowRun has no active DB session")
    try:
        inventory_id = int(str(reference).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{_STEP}: run parameter did not resolve to an inventory id (got {reference!r})"
        ) from exc

    # Fail closed, like start-workflow: PersistenceService checks inventory access only when it is
    # given a username, so a run without a triggering user (a webhook-approved change request)
    # would otherwise read any inventory, including another user's private one (W10-04).
    user = UserRepository(db).get_by_id(run.triggered_by_id) if run.triggered_by_id else None
    if user is None:
        raise ValueError(
            f"{_STEP}: reading an inventory needs the user that triggered this run; "
            "this run has none"
        )
    username = user.username

    source_id = _pick_source_id(db, config)
    credentials = resolve_nautobot_credentials(db, source_id, step_id=_STEP)
    service = service_factory.build_nautobot_source_service(credentials, db)
    logger.info(
        "get-from-user run_id=%s resolving inventory_id=%s source_id=%s",
        log_run_id(run),
        inventory_id,
        source_id,
    )
    try:
        devices = await service.resolve_saved_inventory_devices_by_id(inventory_id, username)
    except PermissionError as exc:
        raise ValueError(
            f"{_STEP}: inventory {inventory_id} is not accessible to the user "
            "that triggered this run"
        ) from exc
    except ValueError as exc:
        raise ValueError(f"{_STEP}: inventory {inventory_id} cannot be used: {exc}") from exc

    lines = [
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
    return "\n".join(lines)
