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


def resolve_ssh_credential(
    db: Session,
    credential_reference: str,
) -> tuple[str, str]:
    """Resolve a credential vault name to (username, password)."""
    reference = credential_reference.strip()
    if not reference:
        raise ValueError("credential_reference is not configured")

    service = CredentialsService(db)
    credentials = service.list_credentials(include_expired=False, source="general")
    match = next((item for item in credentials if item["name"] == reference), None)
    if match is None:
        raise CredentialReferenceNotFoundError(
            f"SSH credential {reference!r} not found in credential vault"
        )
    if match["type"] != "ssh":
        raise CredentialReferenceInvalidError(
            f"Credential {reference!r} must be type 'ssh', got {match['type']!r}"
        )
    if match["status"] == "expired":
        raise CredentialReferenceInvalidError(
            f"Credential {reference!r} is expired"
        )

    try:
        password = service.get_decrypted_password(int(match["id"]))
    except (CredentialNotFoundError, CredentialMissingFieldError) as exc:
        raise CredentialReferenceInvalidError(
            f"Credential {reference!r} has no decryptable password"
        ) from exc

    return str(match["username"]), password
