"""pyATS shim source configuration: pairs a settings entry with a vault credential.

The connection's non-secret settings (URL, verify_ssl, timeout) live in the
generic ``settings`` table under ``sources.pyats.<id>``; the bearer token is a
user-selected credential from the ``credentials`` vault, referenced by
``credential_id``. The credential must be global (see
``services.credentials.source_credentials``). The shim always runs on the internal Docker
network over plain http, so only the SSRF/URL checks apply, not the https/``verify_ssl``
source transport policy. All other behaviour lives in ``services.settings.source_config_base``.
"""

from __future__ import annotations

from core.safe_urls import validate_outbound_http_url
from services.pyats.common.exceptions import PyATSValidationError
from services.pyats.credentials import PyATSCredentials
from services.settings.source_config_base import (
    CredentialedHttpSourceService,
    SourceConflictError,
    SourceNotFoundError,
)


class PyATSSourceNotFoundError(SourceNotFoundError):
    display_name = "pyATS"


class PyATSSourceConflictError(SourceConflictError):
    display_name = "pyATS"


class PyATSSourceConfigService(CredentialedHttpSourceService[PyATSCredentials]):
    source_type = "pyats"
    display_name = "pyATS"
    description_label = "pyATS shim source"
    not_found_error = PyATSSourceNotFoundError
    conflict_error = PyATSSourceConflictError
    validation_error = PyATSValidationError
    default_verify_ssl = False

    def _validate_url(self, url: str, *, verify_ssl: bool) -> str:
        return validate_outbound_http_url(url, resolve_dns=True)

    def _build_credentials(
        self, *, base_url: str, username: str | None, secret: str, timeout: float, verify_ssl: bool
    ) -> PyATSCredentials:
        return PyATSCredentials(
            base_url=base_url,
            token=secret,
            timeout=timeout,
            verify_ssl=verify_ssl,
        )
