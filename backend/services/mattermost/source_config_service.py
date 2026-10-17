"""Mattermost source configuration: pairs a settings entry with a vault credential.

The connection's non-secret settings (URL, verify_ssl, timeout) live in the
generic ``settings`` table under ``sources.mattermost.<id>``; the personal
access token is a user-selected credential from the ``credentials`` vault,
referenced by ``credential_id``. The credential must be global (see
``services.credentials.source_credentials``). All behaviour lives in
``services.settings.source_config_base``.
"""

from __future__ import annotations

from services.mattermost.common.exceptions import MattermostValidationError
from services.mattermost.credentials import MattermostCredentials
from services.settings.source_config_base import (
    CredentialedHttpSourceService,
    SourceConflictError,
    SourceNotFoundError,
)


class MattermostSourceNotFoundError(SourceNotFoundError):
    display_name = "Mattermost"


class MattermostSourceConflictError(SourceConflictError):
    display_name = "Mattermost"


class MattermostSourceConfigService(CredentialedHttpSourceService[MattermostCredentials]):
    source_type = "mattermost"
    display_name = "Mattermost"
    description_label = "Mattermost source"
    not_found_error = MattermostSourceNotFoundError
    conflict_error = MattermostSourceConflictError
    validation_error = MattermostValidationError

    def _build_credentials(
        self, *, base_url: str, username: str | None, secret: str, timeout: float, verify_ssl: bool
    ) -> MattermostCredentials:
        return MattermostCredentials(
            base_url=base_url,
            token=secret,
            timeout=timeout,
            verify_ssl=verify_ssl,
        )
