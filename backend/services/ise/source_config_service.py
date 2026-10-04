"""Cisco ISE source configuration: pairs a settings entry with a vault credential.

The connection's non-secret settings (URL, verify_ssl, timeout) live in the
generic ``settings`` table under ``sources.ise.<id>``; the username + password
are a user-selected credential from the ``credentials`` vault, referenced by
``credential_id``. ISE authenticates with basic auth, so the chosen credential
must carry a non-empty username. The credential must be global (see
``services.credentials.source_credentials``). All behaviour lives in
``services.settings.source_config_base``.
"""

from __future__ import annotations

from services.ise.common.exceptions import ISEValidationError
from services.ise.credentials import ISECredentials
from services.settings.source_config_base import (
    CredentialedHttpSourceService,
    SourceConflictError,
    SourceNotFoundError,
)


class ISESourceNotFoundError(SourceNotFoundError):
    display_name = "ISE"


class ISESourceConflictError(SourceConflictError):
    display_name = "ISE"


class ISESourceConfigService(CredentialedHttpSourceService[ISECredentials]):
    source_type = "ise"
    display_name = "ISE"
    description_label = "Cisco ISE source"
    not_found_error = ISESourceNotFoundError
    conflict_error = ISESourceConflictError
    validation_error = ISEValidationError
    requires_username = True

    def _build_credentials(
        self, *, base_url: str, username: str | None, secret: str, timeout: float, verify_ssl: bool
    ) -> ISECredentials:
        return ISECredentials(
            base_url=base_url,
            username=username or "",
            password=secret,
            timeout=timeout,
            verify_ssl=verify_ssl,
        )
