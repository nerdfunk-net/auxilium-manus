"""Resolve a vault credential for a background source integration.

Thin compatibility shim over :class:`services.credentials.manager.CredentialManager`.
Source integrations (Nautobot / pyATS / Mattermost / ISE) have no acting user
and are also read by background jobs, so they can only use
``visibility="global"`` credentials. New code should call
``CredentialManager(db).source_credential(...)`` / ``.source_secret(...)`` directly.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from services.credentials.manager import CredentialManager
from services.credentials.secrets import CredentialLookupError, CredentialUnusableError


class SourceCredentialError(ValueError):
    """A selected source credential is missing, private, or has no secret."""


def assert_global_credential(db: Session, credential_id: int) -> dict:
    """Return the credential dict for ``credential_id`` or raise if not global."""
    try:
        return CredentialManager(db).source_credential(credential_id)
    except CredentialLookupError as exc:
        raise SourceCredentialError(str(exc)) from exc


def resolve_global_secret(db: Session, credential_id: int) -> tuple[str | None, str]:
    """Return ``(username, password)`` for a global credential, or raise."""
    try:
        secret = CredentialManager(db).source_secret(credential_id)
    except (CredentialLookupError, CredentialUnusableError) as exc:
        raise SourceCredentialError(str(exc)) from exc
    return secret.username, secret.password
