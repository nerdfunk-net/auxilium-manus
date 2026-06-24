"""Symmetric encryption for credentials at rest."""

from __future__ import annotations

import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_KDF_SALT = b"auxilium-credential-encryption-v1"
_KDF_ITERATIONS = int(os.getenv("KDF_ITERATIONS", "100000"))


def _build_key(secret: str, iterations: int = _KDF_ITERATIONS) -> bytes:
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
        self._fernet = Fernet(_build_key(secret))

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, token: bytes) -> str:
        try:
            return self._fernet.decrypt(token).decode("utf-8")
        except InvalidToken as exc:
            raise ValueError("Failed to decrypt stored credential") from exc
