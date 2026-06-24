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
