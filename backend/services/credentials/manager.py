"""Single typed facade over :class:`CredentialsService` for secret resolution.

Historically three parallel modules resolved "a credential reference" to its
secret, each with its own signature, lookup key, visibility rule, and return
shape:

* ``workflow_steps.common.credential_resolver`` — name-keyed, resolves the
  acting user's private credentials then falls back to global.
* ``services.credentials.source_credentials`` — id-keyed, global-only.
* ``services.git.auth.GitAuthenticationService`` — name + ``auth_type`` keyed,
  global-only, forgiving (missing credential -> empty result, not an error).

``CredentialManager`` exposes one method per shape. It does **not** touch the
``storage_backend`` (local Fernet vs OpenBao) dispatch — that lives entirely
inside the four ``CredentialsService.get_decrypted_*`` / ``get_ssh_key_path``
methods and every method here bottoms out there.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from core.passphrase_cipher import normalize_algorithm
from services.credentials.credentials_service import CredentialsService
from services.credentials.exceptions import (
    CredentialMissingFieldError,
    CredentialNotFoundError,
    CredentialVaultNotConfiguredError,
    CredentialVaultUnavailableError,
)
from services.credentials.secrets import (
    CredentialLookupError,
    CredentialUnusableError,
    GenericSecret,
    GitSecret,
    SharedSecret,
    SourceSecret,
    SshSecret,
)

logger = logging.getLogger(__name__)

_SSH_TYPES = frozenset({"ssh"})
_GENERIC_TYPES = frozenset({"ssh", "generic"})
_SHARED_SECRET_TYPES = frozenset({"shared_secret"})

_NOT_GLOBAL = (
    "Selected credential must exist and be global -- source integrations run in "
    "the background and cannot read private credentials."
)


class CredentialManager:
    """Resolve stored credentials to their decrypted secret material.

    Args:
        db: An open SQLAlchemy session.
        acting_user_id: The run's ``triggered_by_id`` for the name-keyed
            methods (:meth:`ssh`, :meth:`generic`, :meth:`shared_secret`).
            ``None`` (schedule/system run, or a background job) scopes those
            to global credentials only. The id-keyed and git methods are
            always global-only and ignore this value.
    """

    def __init__(self, db: Session, *, acting_user_id: int | None = None) -> None:
        self._svc = CredentialsService(db)
        self._acting_user_id = acting_user_id

    # --------------------------------------------------- name-keyed (user-scoped)
    def ssh(self, name: str) -> SshSecret:
        """Resolve an ``ssh`` credential name to ``(username, password)``."""
        match = self._match_by_name(name, _SSH_TYPES, "'ssh'")
        username, password = self._decrypt_password(
            match, name, "has no decryptable password"
        )
        return SshSecret(username=username, password=password)

    def generic(self, name: str) -> GenericSecret:
        """Resolve an ``ssh`` or ``generic`` credential for a non-SSH transport."""
        match = self._match_by_name(name, _GENERIC_TYPES, "'ssh' or 'generic'")
        username, password = self._decrypt_password(
            match, name, "has no decryptable password"
        )
        return GenericSecret(username=username, password=password)

    def shared_secret(self, name: str) -> SharedSecret:
        """Resolve a ``shared_secret`` credential to ``(algorithm, passphrase)``."""
        match = self._match_by_name(name, _SHARED_SECRET_TYPES, "'shared_secret'")
        _, passphrase = self._decrypt_password(
            match, name, "has no stored shared secret"
        )
        return SharedSecret(
            algorithm=normalize_algorithm(match.get("algorithm")),
            passphrase=passphrase,
        )

    # -------------------------------------------------------- id-keyed (global-only)
    def source_credential(self, credential_id: int) -> dict[str, Any]:
        """Return the credential dict for ``credential_id`` or raise if not global."""
        credential = self._svc.get_credential_by_id(credential_id)
        if credential is None or credential.get("visibility") != "global":
            raise CredentialLookupError(_NOT_GLOBAL)
        return credential

    def source_secret(self, credential_id: int) -> SourceSecret:
        """Return ``(username, password)`` for a global credential, or raise."""
        credential = self.source_credential(credential_id)
        try:
            password = self._svc.get_decrypted_password(credential_id)
        except (CredentialNotFoundError, CredentialMissingFieldError) as exc:
            raise CredentialUnusableError(
                "Selected credential has no secret set."
            ) from exc
        return SourceSecret(username=credential.get("username"), password=password)

    # ---------------------------------------------------------- git (global-only)
    def git(self, repository: dict) -> GitSecret:
        """Resolve git auth material from a repository dict.

        Keyed on ``credential_name`` + ``auth_type`` (``token`` default,
        ``ssh_key``, ``generic``), scoped to global credentials only. Unlike
        the name-keyed methods this is forgiving: a missing credential or an
        undecryptable secret yields an empty :class:`GitSecret`, not an error.
        Vault-unavailable errors still propagate so the caller fails loudly.
        """
        auth_type = repository.get("auth_type", "token")
        credential_name = repository.get("credential_name")
        if not credential_name:
            return GitSecret(None, None, None)

        creds = self._svc.list_credentials(include_expired=False, acting_user_id=None)
        wanted_type = {"ssh_key": "ssh_key", "generic": "generic"}.get(auth_type, "token")
        match = next(
            (c for c in creds if c["name"] == credential_name and c["type"] == wanted_type),
            None,
        )
        if match is None:
            logger.warning(
                "Git credential '%s' (type '%s') not found in %s global credentials",
                credential_name,
                wanted_type,
                len(creds),
            )
            return GitSecret(None, None, None)

        username = match.get("username")
        if wanted_type == "ssh_key":
            ssh_key_path = self._svc.get_ssh_key_path(match["id"], acting_user_id=None)
            if ssh_key_path:
                return GitSecret(username=username, token=None, ssh_key_path=ssh_key_path)
            logger.error("SSH key file not found for credential '%s'", credential_name)
            return GitSecret(None, None, None)

        try:
            token = self._svc.get_decrypted_password(match["id"], acting_user_id=None)
        except (CredentialVaultUnavailableError, CredentialVaultNotConfiguredError):
            raise
        except Exception:
            logger.error(
                "Failed to decrypt git credential '%s'", credential_name, exc_info=True
            )
            return GitSecret(None, None, None)
        return GitSecret(username=username, token=token, ssh_key_path=None)

    # ------------------------------------------------------------------- internals
    def _match_by_name(
        self, name: str, allowed_types: frozenset[str], type_label: str
    ) -> dict[str, Any]:
        reference = name.strip()
        if not reference:
            raise ValueError("credential_reference is not configured")

        credentials = self._svc.list_credentials(
            include_expired=False,
            source="general",
            acting_user_id=self._acting_user_id,
        )
        matches = [item for item in credentials if item["name"] == reference]
        if not matches:
            raise CredentialLookupError(
                f"Credential {reference!r} not found in credential vault"
            )
        # A private credential wins over a global one of the same name,
        # mirroring RBAC user-override precedence.
        match = next(
            (item for item in matches if item.get("visibility") == "private"), matches[0]
        )
        if match["type"] not in allowed_types:
            raise CredentialUnusableError(
                f"Credential {reference!r} must be type {type_label}, got {match['type']!r}"
            )
        if match["status"] == "expired":
            raise CredentialUnusableError(f"Credential {reference!r} is expired")
        return match

    def _decrypt_password(
        self, match: dict[str, Any], name: str, failure_reason: str
    ) -> tuple[str, str]:
        try:
            password = self._svc.get_decrypted_password(
                int(match["id"]), acting_user_id=self._acting_user_id
            )
        except (CredentialNotFoundError, CredentialMissingFieldError) as exc:
            raise CredentialUnusableError(
                f"Credential {name.strip()!r} {failure_reason}"
            ) from exc
        return str(match["username"]), password
