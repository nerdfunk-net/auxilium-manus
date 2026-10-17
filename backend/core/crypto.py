"""Symmetric encryption for credentials at rest.

Values are ``AMS2.<iterations>.<fernet token>``: the format is versioned and carries the PBKDF2
iteration count it was made with. There is deliberately no compatibility path for the older bare
Fernet format (values stored by an earlier version must be entered again).

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

from core import crypto_policy

# Domain separation from the v1 derivation. The salt is static on purpose (a per-record salt would
# cost one 600k-iteration derivation per decrypt, thousands per run); that is acceptable because
# the input is the random 32+ character CREDENTIAL_ENCRYPTION_KEY enforced at startup. The format
# is versioned and every value names its iteration count.
_KDF_SALT = b"auxilium-credential-encryption-v2"
_PREFIX = "AMS2"
_DECRYPT_ERROR = (
    "Failed to decrypt stored credential "
    "(values stored by an older version must be entered again)"
)


def _iterations() -> int:
    # Late import: avoids a core.config <-> core.crypto import cycle at module load.
    from core.config import settings

    return settings.kdf_iterations


@functools.lru_cache(maxsize=8)
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
    """``encrypt`` returns ``AMS2.<iterations>.<fernet token>`` (ASCII bytes)."""

    def __init__(self, secret_key: str | None = None) -> None:
        self._secret = secret_key or resolve_credential_secret()
        self._iterations = _iterations()
        self._fernet = Fernet(_build_key(self._secret, self._iterations))

    def encrypt(self, plaintext: str) -> bytes:
        token = self._fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")
        return f"{_PREFIX}.{self._iterations}.{token}".encode("ascii")

    def decrypt(self, token: bytes) -> str:
        try:
            prefix, iterations_text, body = bytes(token).decode("ascii").split(".", 2)
            iterations = int(iterations_text) if iterations_text.isdigit() else -1
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError(_DECRYPT_ERROR) from exc
        floor = crypto_policy.KDF_ITERATIONS_FLOOR
        # A downgrade (below the floor) or a CPU bomb (above the ceiling) is refused without
        # deriving anything.
        if prefix != _PREFIX or not floor <= iterations <= crypto_policy.KDF_ITERATIONS_CEILING:
            raise ValueError(_DECRYPT_ERROR)
        try:
            fernet = Fernet(_build_key(self._secret, iterations))
            return fernet.decrypt(body.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as exc:
            raise ValueError(_DECRYPT_ERROR) from exc
