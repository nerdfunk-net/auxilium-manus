"""Portable symmetric encryption keyed by a user-held shared secret (passphrase).

This is deliberately separate from :mod:`core.crypto` (credential-table encryption):

- :mod:`core.crypto` protects data at rest with a **high-entropy server key**
  (``CREDENTIAL_ENCRYPTION_KEY`` / ``SECRET_KEY``) and a static KDF salt.
- This module protects an **attribute value** with a **low-entropy operator
  passphrase**, so every token carries its own random salt and nonce and is
  self-describing. The passphrase is stored once in the credential vault as a
  ``shared_secret`` credential and referenced by name — never baked into a
  workflow definition.

Consumed by the credential validation layer, the ``encrypt-attribute`` /
``decrypt-attribute`` workflow steps, and their editor "Test" endpoints.

Token format (dot-joined, URL-safe base64 without padding)::

    AM1.<algorithm>.<salt_b64>.<nonce_b64>.<ciphertext_b64>

``AM1`` is the envelope version. Because the algorithm is embedded, a stored
token can always be decrypted without knowing the credential's configured
algorithm; when the caller does pass one it is cross-checked.

Adding an algorithm later: add a branch to ``_encrypt`` / ``_decrypt`` and an
entry to :data:`SUPPORTED_ALGORITHMS` / :data:`ALGORITHM_LABELS`.
"""

from __future__ import annotations

import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

_ENVELOPE_VERSION = "AM1"

ALGORITHM_AES_256_GCM = "aes-256-gcm"

DEFAULT_ALGORITHM = ALGORITHM_AES_256_GCM
SUPPORTED_ALGORITHMS: frozenset[str] = frozenset({ALGORITHM_AES_256_GCM})
ALGORITHM_LABELS: dict[str, str] = {
    ALGORITHM_AES_256_GCM: "AES-256-GCM (PBKDF2-SHA256)",
}

_SALT_BYTES = 16
_NONCE_BYTES = 12
_KEY_BYTES = 32


class PassphraseCipherError(ValueError):
    """Raised for a malformed token, unknown/mismatched algorithm, or a failed
    decryption (wrong passphrase / tampered ciphertext). Never contains secret
    material."""


def normalize_algorithm(value: str | None) -> str:
    """Blank/``None`` -> :data:`DEFAULT_ALGORITHM`; unknown -> error."""
    if value is None:
        return DEFAULT_ALGORITHM
    candidate = value.strip().lower()
    if not candidate:
        return DEFAULT_ALGORITHM
    if candidate not in SUPPORTED_ALGORITHMS:
        raise PassphraseCipherError(f"unsupported algorithm: {value!r}")
    return candidate


def algorithm_of_token(token: str) -> str:
    """Return the algorithm embedded in a token, or raise for a malformed one."""
    parts = str(token).strip().split(".")
    if len(parts) != 5 or parts[0] != _ENVELOPE_VERSION:
        raise PassphraseCipherError("malformed token: unexpected envelope")
    return normalize_algorithm(parts[1])


def _pbkdf2_iterations() -> int:
    # Late import: avoid a core.config <-> core.passphrase_cipher cycle at load.
    from core.config import settings

    return settings.kdf_iterations


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64d(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    try:
        return base64.urlsafe_b64decode(text + padding)
    except (ValueError, TypeError) as exc:
        raise PassphraseCipherError("malformed token: bad base64 segment") from exc


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=_KEY_BYTES,
        salt=salt,
        iterations=_pbkdf2_iterations(),
    )
    return kdf.derive(passphrase.encode("utf-8"))


def encrypt_with_passphrase(
    plaintext: str,
    passphrase: str,
    *,
    algorithm: str | None = DEFAULT_ALGORITHM,
) -> str:
    """Encrypt *plaintext* under *passphrase*, returning a self-describing token."""
    if not passphrase:
        raise PassphraseCipherError("passphrase is required")
    algo = normalize_algorithm(algorithm)

    salt = os.urandom(_SALT_BYTES)
    nonce = os.urandom(_NONCE_BYTES)
    key = _derive_key(passphrase, salt)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), None)

    return ".".join(
        (_ENVELOPE_VERSION, algo, _b64e(salt), _b64e(nonce), _b64e(ciphertext))
    )


def decrypt_with_passphrase(
    token: str,
    passphrase: str,
    *,
    algorithm: str | None = None,
) -> str:
    """Decrypt a token produced by :func:`encrypt_with_passphrase`.

    If *algorithm* is given it must match the token's embedded algorithm.
    """
    if not passphrase:
        raise PassphraseCipherError("passphrase is required")

    parts = str(token).strip().split(".")
    if len(parts) != 5 or parts[0] != _ENVELOPE_VERSION:
        raise PassphraseCipherError("malformed token: unexpected envelope")

    _, token_algo, salt_b64, nonce_b64, ct_b64 = parts
    token_algo = normalize_algorithm(token_algo)
    if algorithm is not None and normalize_algorithm(algorithm) != token_algo:
        raise PassphraseCipherError(
            "algorithm mismatch: token was encrypted with a different algorithm"
        )

    salt = _b64d(salt_b64)
    nonce = _b64d(nonce_b64)
    ciphertext = _b64d(ct_b64)

    key = _derive_key(passphrase, salt)
    try:
        plaintext = AESGCM(key).decrypt(nonce, ciphertext, None)
    except InvalidTag as exc:
        raise PassphraseCipherError(
            "decryption failed: wrong shared secret or corrupted value"
        ) from exc
    return plaintext.decode("utf-8")
