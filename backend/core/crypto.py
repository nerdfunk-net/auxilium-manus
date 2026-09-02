"""Symmetric encryption for credentials at rest.

Key derivation uses PBKDF2-HMAC-SHA256 with a **static** salt (``_KDF_SALT``).
A static salt is acceptable here because the input secret
(``CREDENTIAL_ENCRYPTION_KEY``) is a high-entropy random value, not a user
password — the KDF's job is key-stretching and domain separation from
``SECRET_KEY``, not defence against a low-entropy dictionary attack. Rotating
the salt would invalidate every stored ciphertext; treat a salt change as a
deliberate migration that re-encrypts the credentials table.

The derived Fernet key is cached per ``(secret, iterations)`` pair so PBKDF2
runs once per process rather than on every ``EncryptionService()`` construction
(i.e. once, not once per credentials request).
"""

from __future__ import annotations

import base64
import functools
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_KDF_SALT = b"auxilium-credential-encryption-v1"


def _iterations() -> int:
    # Late import: avoids a core.config <-> core.crypto import cycle at module load.
    from core.config import settings

    return settings.kdf_iterations


@functools.lru_cache(maxsize=4)
def _build_key(secret: str, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        iterations=iterations,
    )
    return base64.urlsafe_b64encode(kdf.derive(secret.encode("utf-8")))


def resolve_credential_secret(explicit: str | None = None) -> str:
    secret = explicit or os.getenv("CREDENTIAL_ENCRYPTION_KEY") or os.getenv("SECRET_KEY")
    if not secret:
        raise RuntimeError(
            "No credential encryption secret available. Set CREDENTIAL_ENCRYPTION_KEY "
            "or SECRET_KEY."
        )
    return secret


class EncryptionService:
    def __init__(self, secret_key: str | None = None) -> None:
        secret = secret_key or resolve_credential_secret()
        self._fernet = Fernet(_build_key(secret, _iterations()))

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Failed to decrypt stored credential") from exc
