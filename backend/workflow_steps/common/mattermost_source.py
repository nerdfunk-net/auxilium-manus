"""Shared Mattermost source credential resolution for notification steps."""

from __future__ import annotations

from sqlalchemy.orm import Session

import service_factory
from services.mattermost.common.exceptions import MattermostValidationError
from services.mattermost.credentials import MattermostCredentials
from workflow_steps.common.source_credentials import resolve_source


def resolve_mattermost_credentials(
    db: Session, source_id: str, *, step_id: str
) -> MattermostCredentials:
    """Resolve a configured Mattermost source's credentials.

    Raises ``ValueError`` for configuration errors (unknown source, invalid
    source config) — shared by ``notify-mattermost`` and ``notify-on-error``
    so both raise the same error for the same condition.
    """
    config_service = service_factory.build_mattermost_source_config_service(db)
    return resolve_source(
        config_service, source_id, step_id=step_id, invalid=MattermostValidationError
    )
