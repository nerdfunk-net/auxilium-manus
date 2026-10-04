"""Resolve a vault credential for a background source integration.

Thin compatibility shim over :class:`services.credentials.manager.CredentialManager`.
Source integrations (Nautobot / pyATS / Mattermost / ISE / Catalyst Center) have no acting user
and are also read by background jobs, so they can only use ``visibility="global"`` credentials,
and only of the type the integration authenticates with (``SOURCE_CREDENTIAL_TYPES``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from services.credentials.manager import CredentialManager
from services.credentials.secrets import CredentialLookupError, CredentialUnusableError

if TYPE_CHECKING:
    # Type-only: ``services.settings`` imports this module (settings_service), so a runtime
    # import here would be circular.
    from services.settings.source_keys import SourceType

# What the five source dialogs offer (``CredentialSelect credentialType=…``): bearer-token
# sources take a ``token`` credential, basic-auth sources a ``generic`` one.
SOURCE_CREDENTIAL_TYPES: dict[str, frozenset[str]] = {
    "nautobot": frozenset({"token"}),
    "mattermost": frozenset({"token"}),
    "pyats": frozenset({"token"}),
    "ise": frozenset({"generic"}),
    "catalyst_center": frozenset({"generic"}),
}


class SourceCredentialError(ValueError):
    """A selected source credential is missing, private, of the wrong type, or has no secret."""


def assert_global_credential(db: Session, credential_id: int, *, source_type: SourceType) -> dict:
    """Return the credential dict for ``credential_id`` or raise if not global / wrong type."""
    try:
        return CredentialManager(db).source_credential(
            credential_id, allowed_types=SOURCE_CREDENTIAL_TYPES[source_type]
        )
    except (CredentialLookupError, CredentialUnusableError) as exc:
        raise SourceCredentialError(str(exc)) from exc


def resolve_global_secret(
    db: Session, credential_id: int, *, source_type: SourceType
) -> tuple[str | None, str]:
    """Return ``(username, password)`` for a global credential of the right type, or raise."""
    try:
        secret = CredentialManager(db).source_secret(
            credential_id, allowed_types=SOURCE_CREDENTIAL_TYPES[source_type]
        )
    except (CredentialLookupError, CredentialUnusableError) as exc:
        raise SourceCredentialError(str(exc)) from exc
    return secret.username, secret.password
