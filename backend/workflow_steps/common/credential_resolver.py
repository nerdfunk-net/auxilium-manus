"""Resolve stored vault credentials for workflow steps."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from core.passphrase_cipher import normalize_algorithm
from services.credentials.credentials_service import CredentialsService
from services.credentials.exceptions import (
    CredentialMissingFieldError,
    CredentialNotFoundError,
)


class CredentialReferenceNotFoundError(ValueError):
    """Raised when a credential name does not exist in the vault."""


class CredentialReferenceInvalidError(ValueError):
    """Raised when a credential exists but is not usable for the requested purpose."""


def _resolve_credential_row(
    db: Session,
    credential_reference: str,
    *,
    acting_user_id: int | None,
    allowed_types: frozenset[str],
    type_error_label: str,
) -> tuple[dict[str, Any], CredentialsService]:
    """Find a visible credential by name and return ``(row, service)``.

    Resolution is scoped to global credentials plus the acting user's own
    private credentials. ``acting_user_id`` should be the executing run's
    ``triggered_by_id``; if it is ``None`` (schedule/system run) only global
    credentials resolve. A private credential wins over a global one of the
    same name, mirroring RBAC user-override precedence.
    """
    reference = credential_reference.strip()
    if not reference:
        raise ValueError("credential_reference is not configured")

    service = CredentialsService(db)
    credentials = service.list_credentials(
        include_expired=False, source="general", acting_user_id=acting_user_id
    )
    matches = [item for item in credentials if item["name"] == reference]
    if not matches:
        raise CredentialReferenceNotFoundError(
            f"Credential {reference!r} not found in credential vault"
        )
    match = next(
        (item for item in matches if item.get("visibility") == "private"), matches[0]
    )
    if match["type"] not in allowed_types:
        raise CredentialReferenceInvalidError(
            f"Credential {reference!r} must be type {type_error_label}, got {match['type']!r}"
        )
    if match["status"] == "expired":
        raise CredentialReferenceInvalidError(f"Credential {reference!r} is expired")
    return match, service


def _resolve_credential(
    db: Session,
    credential_reference: str,
    *,
    acting_user_id: int | None,
    allowed_types: frozenset[str],
    type_error_label: str,
) -> tuple[str, str]:
    match, service = _resolve_credential_row(
        db,
        credential_reference,
        acting_user_id=acting_user_id,
        allowed_types=allowed_types,
        type_error_label=type_error_label,
    )
    try:
        password = service.get_decrypted_password(
            int(match["id"]), acting_user_id=acting_user_id
        )
    except (CredentialNotFoundError, CredentialMissingFieldError) as exc:
        raise CredentialReferenceInvalidError(
            f"Credential {credential_reference.strip()!r} has no decryptable password"
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


def resolve_shared_secret_credential(
    db: Session,
    credential_reference: str,
    *,
    acting_user_id: int | None,
) -> tuple[str, str]:
    """Resolve a ``shared_secret`` credential to ``(algorithm, passphrase)``.

    Same visibility/precedence/expiry rules as ``resolve_ssh_credential``. The
    passphrase is stored in the credential's password field; ``algorithm`` is
    the credential's configured symmetric algorithm (defaulted when unset).
    """
    match, service = _resolve_credential_row(
        db,
        credential_reference,
        acting_user_id=acting_user_id,
        allowed_types=frozenset({"shared_secret"}),
        type_error_label="'shared_secret'",
    )
    try:
        passphrase = service.get_decrypted_password(
            int(match["id"]), acting_user_id=acting_user_id
        )
    except (CredentialNotFoundError, CredentialMissingFieldError) as exc:
        raise CredentialReferenceInvalidError(
            f"Credential {credential_reference.strip()!r} has no stored shared secret"
        ) from exc
    algorithm = normalize_algorithm(match.get("algorithm"))
    return algorithm, passphrase
