"""Cisco Catalyst Center source configuration: a settings entry plus a vault credential.

Non-secret connection settings (URL, verify_ssl, timeout) live in the generic ``settings``
table under ``sources.catalyst_center.<id>``; the username + password are a user-selected
credential from the ``credentials`` vault, referenced by ``credential_id``. Catalyst Center's
token endpoint uses HTTP Basic auth, so the credential must carry a username. The credential
must be global (see ``services.credentials.source_credentials``). All behaviour lives in
``services.settings.source_config_base``.
"""

from __future__ import annotations

from services.catalyst_center.common.exceptions import CatalystCenterValidationError
from services.catalyst_center.credentials import CatalystCenterCredentials
from services.settings.source_config_base import (
    CredentialedHttpSourceService,
    SourceConflictError,
    SourceNotFoundError,
)


class CatalystCenterSourceNotFoundError(SourceNotFoundError):
    display_name = "Catalyst Center"


class CatalystCenterSourceConflictError(SourceConflictError):
    display_name = "Catalyst Center"


class CatalystCenterSourceConfigService(CredentialedHttpSourceService[CatalystCenterCredentials]):
    source_type = "catalyst_center"
    display_name = "Catalyst Center"
    description_label = "Cisco Catalyst Center source"
    not_found_error = CatalystCenterSourceNotFoundError
    conflict_error = CatalystCenterSourceConflictError
    validation_error = CatalystCenterValidationError
    requires_username = True

    def _build_credentials(
        self, *, base_url: str, username: str | None, secret: str, timeout: float, verify_ssl: bool
    ) -> CatalystCenterCredentials:
        return CatalystCenterCredentials(
            base_url=base_url,
            username=username or "",
            password=secret,
            timeout=timeout,
            verify_ssl=verify_ssl,
        )
