"""Shared Mattermost source credential resolution for notification steps."""

from __future__ import annotations

from sqlalchemy.orm import Session

import service_factory
from services.mattermost.common.exceptions import MattermostValidationError
from services.mattermost.credentials import MattermostCredentials
from services.mattermost.source_config_service import MattermostSourceNotFoundError


def resolve_mattermost_credentials(
    db: Session, source_id: str, *, step_id: str
) -> MattermostCredentials:
    """Resolve a configured Mattermost source's credentials.

    Raises ``ValueError`` for configuration errors (unknown source, invalid
    source config) — shared by ``notify-mattermost`` and ``notify-on-error``
    so both raise the same error for the same condition.
    """
    config_service = service_factory.build_mattermost_source_config_service(db)
    try:
        return config_service.resolve_credentials(source_id)
    except MattermostSourceNotFoundError as exc:
        raise ValueError(f"{step_id}: Mattermost source '{source_id}' not found") from exc
    except MattermostValidationError as exc:
        raise ValueError(f"{step_id}: {exc}") from exc
