"""Resolve stored SSH credentials for workflow steps."""

from __future__ import annotations

from sqlalchemy.orm import Session

from services.credentials.credentials_service import CredentialsService
from services.credentials.exceptions import (
    CredentialMissingFieldError,
    CredentialNotFoundError,
)


class CredentialReferenceNotFoundError(ValueError):
    """Raised when a credential name does not exist in the vault."""


class CredentialReferenceInvalidError(ValueError):
    """Raised when a credential exists but is not usable for SSH."""


def _resolve_credential(
    db: Session,
    credential_reference: str,
    *,
    acting_user_id: int | None,
    allowed_types: frozenset[str],
    type_error_label: str,
) -> tuple[str, str]:
    reference = credential_reference.strip()
    if not reference:
        raise ValueError("credential_reference is not configured")

    service = CredentialsService(db)
    credentials = service.list_credentials(
        include_expired=False, source="general", acting_user_id=acting_user_id
    )
    match = next((item for item in credentials if item["name"] == reference), None)
    if match is None:
        raise CredentialReferenceNotFoundError(
            f"Credential {reference!r} not found in credential vault"
        )
    if match["type"] not in allowed_types:
        raise CredentialReferenceInvalidError(
            f"Credential {reference!r} must be type {type_error_label}, got {match['type']!r}"
        )
    if match["status"] == "expired":
        raise CredentialReferenceInvalidError(f"Credential {reference!r} is expired")

    try:
        password = service.get_decrypted_password(int(match["id"]), acting_user_id=acting_user_id)
    except (CredentialNotFoundError, CredentialMissingFieldError) as exc:
        raise CredentialReferenceInvalidError(
            f"Credential {reference!r} has no decryptable password"
        ) from exc

    return str(match["username"]), password


def resolve_ssh_credential(
    db: Session,
    credential_reference: str,
    *,
    acting_user_id: int | None,
) -> tuple[str, str]:
    """Resolve a credential vault name to (username, password), scoped to
    global credentials plus the acting user's own private credentials.

    ``acting_user_id`` should be the executing run's ``triggered_by_id``. If
    it is ``None`` (e.g. a schedule/system-triggered run with no user), only
    global credentials resolve.
    """
    return _resolve_credential(
        db,
        credential_reference,
        acting_user_id=acting_user_id,
        allowed_types=frozenset({"ssh"}),
        type_error_label="'ssh'",
    )


def resolve_generic_credential(
    db: Session,
    credential_reference: str,
    *,
    acting_user_id: int | None,
) -> tuple[str, str]:
    """Like ``resolve_ssh_credential``, but for consumers that need a plain
    username/password pair over a non-SSH transport (e.g. the pyATS shim's
    HTTP API) rather than an actual SSH session.

    Accepts both ``"ssh"`` and ``"generic"`` credential types, so an existing
    SSH credential already used for Netmiko steps can be reused here without
    creating a duplicate vault entry.
    """
    return _resolve_credential(
        db,
        credential_reference,
        acting_user_id=acting_user_id,
        allowed_types=frozenset({"ssh", "generic"}),
        type_error_label="'ssh' or 'generic'",
    )
