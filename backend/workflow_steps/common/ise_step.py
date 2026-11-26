"""What every Cisco ISE step does before its first device: credentials, service, pre-flight (W6-03).

``get-ise-devices`` (Get from ISE), ``add-to-ise`` (Add to ISE), ``get-ise-tacacs-key`` (Get
TACACS+ Key from ISE) and ``update-ise-tacacs-key`` (Update TACACS+ Key in ISE) resolve the
configured source the same way and refuse to start when ISE cannot be reached.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

import service_factory
from models.workflow_context import StepOutcome, WorkflowContext
from services.ise.common.exceptions import ISEAPIError, ISEValidationError
from services.ise.credentials import ISECredentials
from workflow_steps.common.run_session import require_session
from workflow_steps.common.source_credentials import resolve_source

if TYPE_CHECKING:
    from core.models.runs import WorkflowRun
    from services.ise.network_device_service import ISENetworkDeviceService

logger = logging.getLogger(__name__)


def resolve_ise_credentials(db: Session, source_id: str, *, step_id: str) -> ISECredentials:
    """Credentials of ``source_id``; an unknown or incomplete source is a ``ValueError``."""
    return resolve_source(
        service_factory.build_ise_source_config_service(db),
        source_id,
        step_id=step_id,
        invalid=ISEValidationError,
    )


def ise_credentials(run: WorkflowRun, source_id: str, *, step_id: str) -> ISECredentials:
    """``resolve_ise_credentials`` with the run's session (a run without one is a bug)."""
    return resolve_ise_credentials(require_session(run, step_id), source_id, step_id=step_id)


def build_ise_device_service(
    run: WorkflowRun, source_id: str, *, step_id: str
) -> ISENetworkDeviceService:
    """The network-device service of ``source_id`` for ``run``."""
    return service_factory.build_ise_network_device_service(
        ise_credentials(run, source_id, step_id=step_id)
    )


async def preflight_ise(
    device_service: ISENetworkDeviceService,
    context: WorkflowContext,
    source_id: str,
    *,
    step_id: str,
) -> list[StepOutcome] | None:
    """``None`` when ISE answers; otherwise one ``failure`` outcome for the whole context, with
    the transport cause: no device was touched, so every device leaves the same way."""
    try:
        await device_service.test_connection()
    except ISEAPIError as exc:
        logger.warning("%s: could not reach ISE source '%s': %s", step_id, source_id, exc)
        return [
            StepOutcome(
                name="failure",
                context=context,
                summary=f"could not reach ISE source '{source_id}': {exc}",
                failure=exc.failure,
            )
        ]
    return None
