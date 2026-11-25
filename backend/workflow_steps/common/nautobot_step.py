"""Binding a run to a Nautobot source: the preamble the Nautobot steps shared (W5-06).

Each Nautobot step needs the same three things before its first call: the run's database session,
the credentials of the configured source and a client that carries them. The step keeps a one-line
``_bind_nautobot`` that wraps the client in whatever service it uses.
"""

from __future__ import annotations

from dataclasses import dataclass

import service_factory
from core.models.runs import WorkflowRun
from services.nautobot.client import NautobotService
from services.nautobot.credentials import NautobotCredentials
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.run_session import require_session


@dataclass(frozen=True)
class NautobotBinding:
    """What a Nautobot step needs before its first call: credentials, service and a client."""

    credentials: NautobotCredentials
    service: NautobotService
    client: CredentialsBoundNautobotClient


def bind_nautobot(run: WorkflowRun, source_id: str, *, step_id: str) -> NautobotBinding:
    """Credentials, service and client of ``source_id`` for ``run``; no session is a bug."""
    db = require_session(run, step_id)
    credentials = resolve_nautobot_credentials(db, source_id, step_id=step_id)
    service = service_factory.get_nautobot_app_service()
    client = CredentialsBoundNautobotClient(service, credentials)
    return NautobotBinding(credentials, service, client)


def bind_nautobot_client(
    run: WorkflowRun, source_id: str, *, step_id: str
) -> CredentialsBoundNautobotClient:
    """The Nautobot client of ``source_id`` for ``run``; a run without a session is a bug."""
    return bind_nautobot(run, source_id, step_id=step_id).client
