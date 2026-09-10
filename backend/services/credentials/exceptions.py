"""Typed exceptions for credential services."""

from __future__ import annotations


class CredentialNotFoundError(Exception):
    def __init__(self, cred_id: int) -> None:
        super().__init__(f"Credential {cred_id} not found")
        self.cred_id = cred_id


class CredentialMissingFieldError(Exception):
    """Raised when a requested decrypted field (password, SSH key) is absent."""


class CredentialNameConflictError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Credential name '{name}' already exists")
        self.name = name


class CredentialVaultUnavailableError(Exception):
    """Raised when a vault-backed credential cannot be served (fail closed).

    Wraps a ``services.vault.exceptions.VaultError`` so router code can map it to
    a 503 without importing the vault package.
    """


class CredentialStorageBackendChangeError(Exception):
    """Raised when an update tries to move a credential between local and vault."""

    def __init__(self) -> None:
        super().__init__("Changing the storage backend of an existing credential is not supported")


class CredentialVaultNotConfiguredError(Exception):
    """Raised when a vault-backed operation is requested but OpenBao is not configured."""

    def __init__(self) -> None:
        super().__init__("Vault storage is not configured on this deployment")
