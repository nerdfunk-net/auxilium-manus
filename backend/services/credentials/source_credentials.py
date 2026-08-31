"""Resolve a vault credential for a background source integration.

Source integrations (Nautobot / pyATS / Mattermost / ISE) have no acting user
and are also read by background jobs, so they can only use
``visibility="global"`` credentials -- identical to the Git repository
credential rule (``services.git.auth``). These helpers turn a user-selected
``credential_id`` into its secret and fail with a clear error instead of the
silent "not found" that private credentials produce when resolved with
``acting_user_id=None``.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from services.credentials.credentials_service import CredentialsService
from services.credentials.exceptions import CredentialMissingFieldError

_NOT_GLOBAL = (
    "Selected credential must exist and be global -- source integrations run in "
    "the background and cannot read private credentials."
)


class SourceCredentialError(ValueError):
    """A selected source credential is missing, private, or has no secret."""


def assert_global_credential(db: Session, credential_id: int) -> dict:
    """Return the credential dict for ``credential_id`` or raise if not global."""
    credential = CredentialsService(db).get_credential_by_id(credential_id)
    if credential is None or credential.get("visibility") != "global":
        raise SourceCredentialError(_NOT_GLOBAL)
    return credential


def resolve_global_secret(db: Session, credential_id: int) -> tuple[str | None, str]:
    """Return ``(username, password)`` for a global credential, or raise."""
    service = CredentialsService(db)
    credential = service.get_credential_by_id(credential_id)
    if credential is None or credential.get("visibility") != "global":
        raise SourceCredentialError(_NOT_GLOBAL)
    try:
        password = service.get_decrypted_password(credential_id)
    except CredentialMissingFieldError as exc:
        raise SourceCredentialError("Selected credential has no secret set.") from exc
    return credential.get("username"), password
