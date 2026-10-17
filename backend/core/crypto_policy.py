"""KDF iteration bounds shared by the credential store and the passphrase cipher (S3-09).

No imports from ``core.config``: both ``core.config`` and the crypto modules import this."""

from __future__ import annotations

# OWASP 2023 guidance for PBKDF2-HMAC-SHA256. Every ciphertext stores the count it was made with,
# so raising the default later never breaks old values.
KDF_ITERATIONS_FLOOR = 600_000
# A hostile token cannot make the server derive with more than this.
KDF_ITERATIONS_CEILING = 5_000_000
