"""Cisco ACI (APIC) source configuration: a settings entry plus a vault credential.

Non-secret connection settings (URL, verify_ssl, timeout) live in the generic ``settings``
table under ``sources.aci.<id>``; the username + password are a user-selected credential from the
``credentials`` vault, referenced by ``credential_id``. The APIC login takes a user name and a
password, so the credential must carry a username. For a remote (non-local) APIC user, put the
login domain into the credential's username as ``apic:<domain>\\<user>``. The credential must be
global (see ``services.credentials.source_credentials``). All behaviour lives in
``services.settings.source_config_base``.
"""

from __future__ import annotations

from services.aci.common.exceptions import AciValidationError
from services.aci.credentials import AciCredentials
from services.settings.source_config_base import (
    CredentialedHttpSourceService,
    SourceConflictError,
    SourceNotFoundError,
)


class AciSourceNotFoundError(SourceNotFoundError):
    display_name = "Cisco ACI"


class AciSourceConflictError(SourceConflictError):
    display_name = "Cisco ACI"


class AciSourceConfigService(CredentialedHttpSourceService[AciCredentials]):
    source_type = "aci"
    display_name = "Cisco ACI"
    description_label = "Cisco ACI source"
    not_found_error = AciSourceNotFoundError
    conflict_error = AciSourceConflictError
    validation_error = AciValidationError
    requires_username = True

    def _build_credentials(
        self, *, base_url: str, username: str | None, secret: str, timeout: float, verify_ssl: bool
    ) -> AciCredentials:
        return AciCredentials(
            base_url=base_url,
            username=username or "",
            password=secret,
            timeout=timeout,
            verify_ssl=verify_ssl,
        )
