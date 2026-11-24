"""Binding a run to a Nautobot source: the preamble the Nautobot steps shared (W5-06).

Each Nautobot step needs the same three things before its first call: the run's database session,
the credentials of the configured source and a client that carries them. The step keeps a one-line
``_bind_nautobot`` that wraps the client in whatever service it uses.
"""

from __future__ import annotations

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials


def bind_nautobot_client(
    run: WorkflowRun, source_id: str, *, step_id: str
) -> CredentialsBoundNautobotClient:
    """The Nautobot client of ``source_id`` for ``run``; a run without a session is a bug."""
    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{step_id}: WorkflowRun has no active DB session")
    credentials = resolve_nautobot_credentials(db, source_id, step_id=step_id)
    return CredentialsBoundNautobotClient(service_factory.get_nautobot_app_service(), credentials)
