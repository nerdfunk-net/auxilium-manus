"""Resolve stored vault credentials for workflow steps.

Thin compatibility shim over :class:`services.credentials.manager.CredentialManager`.
The typed facade is the single resolution path now; these functions keep the
tuple return shape and the ``CredentialReference*`` error types that workflow
executors already depend on. New code should call ``CredentialManager`` directly.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from services.credentials.manager import CredentialManager
from services.credentials.secrets import CredentialLookupError, CredentialUnusableError


class CredentialReferenceNotFoundError(ValueError):
    """Raised when a credential name does not exist in the vault."""


class CredentialReferenceInvalidError(ValueError):
    """Raised when a credential exists but is not usable for the requested purpose."""


def _translate(call):
    """Run ``call`` and remap facade errors to the legacy ``CredentialReference*`` types."""
    try:
        return call()
    except CredentialLookupError as exc:
        raise CredentialReferenceNotFoundError(str(exc)) from exc
    except CredentialUnusableError as exc:
        raise CredentialReferenceInvalidError(str(exc)) from exc


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
    secret = _translate(
        lambda: CredentialManager(db, acting_user_id=acting_user_id).ssh(credential_reference)
    )
    return secret.username, secret.password


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
    secret = _translate(
        lambda: CredentialManager(db, acting_user_id=acting_user_id).generic(
            credential_reference
        )
    )
    return secret.username, secret.password


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
    secret = _translate(
        lambda: CredentialManager(db, acting_user_id=acting_user_id).shared_secret(
            credential_reference
        )
    )
    return secret.algorithm, secret.passphrase
