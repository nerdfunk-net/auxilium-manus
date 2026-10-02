"""Cisco IOS password formats for the encrypt/decrypt-attribute steps.

Unlike :mod:`core.passphrase_cipher` these need **no shared secret**:

- ``cisco-type7`` — legacy reversible XOR obfuscation (tacacs/radius keys,
  ``password 7 ...``). Not real encryption; anyone can decode it.
- ``cisco-type8`` — PBKDF2-SHA256 one-way hash (``secret 8 $8$salt$hash``).
- ``cisco-type9`` — scrypt one-way hash (``secret 9 $9$salt$hash``).

Types 8 and 9 are one-way and can never be decrypted. Implemented on top of the
``network-secret`` package. These names are deliberately **not** part of
``passphrase_cipher.SUPPORTED_ALGORITHMS``: a ``shared_secret`` credential cannot
be configured with a keyless algorithm.
"""

from __future__ import annotations

from network_secret import cisco_type7, cisco_type8, cisco_type9

ALGORITHM_CISCO_TYPE7 = "cisco-type7"
ALGORITHM_CISCO_TYPE8 = "cisco-type8"
ALGORITHM_CISCO_TYPE9 = "cisco-type9"

CISCO_ALGORITHMS: frozenset[str] = frozenset(
    {ALGORITHM_CISCO_TYPE7, ALGORITHM_CISCO_TYPE8, ALGORITHM_CISCO_TYPE9}
)
CISCO_ALGORITHM_LABELS: dict[str, str] = {
    ALGORITHM_CISCO_TYPE7: "Cisco type 7 (reversible obfuscation)",
    ALGORITHM_CISCO_TYPE8: "Cisco type 8 (PBKDF2-SHA256, one-way)",
    ALGORITHM_CISCO_TYPE9: "Cisco type 9 (scrypt, one-way)",
}

_ENCRYPTORS = {
    ALGORITHM_CISCO_TYPE7: cisco_type7.encrypt,
    ALGORITHM_CISCO_TYPE8: cisco_type8.encrypt,
    ALGORITHM_CISCO_TYPE9: cisco_type9.encrypt,
}


class CiscoSecretError(ValueError):
    """Unknown/unsupported Cisco algorithm or an unencodable/malformed value.
    Never contains the cleartext."""


def is_cisco_algorithm(value: str | None) -> bool:
    return bool(value) and value.strip().lower() in CISCO_ALGORITHMS


def _normalize(algorithm: str) -> str:
    candidate = str(algorithm).strip().lower()
    if candidate not in CISCO_ALGORITHMS:
        raise CiscoSecretError(f"unsupported cisco algorithm: {algorithm!r}")
    return candidate


def encrypt_cisco(plaintext: str, algorithm: str) -> str:
    """Encode (type 7) or hash (types 8/9) *plaintext* in Cisco config format."""
    algo = _normalize(algorithm)
    try:
        return _ENCRYPTORS[algo](plaintext)
    except ValueError as exc:
        # The library's type 7 message names the problem, not the value.
        raise CiscoSecretError(str(exc)) from exc


def decrypt_cisco(token: str, algorithm: str) -> str:
    """Decode a type 7 value. Types 8/9 are one-way hashes and always raise."""
    algo = _normalize(algorithm)
    if algo != ALGORITHM_CISCO_TYPE7:
        raise CiscoSecretError(
            f"{algo} is a one-way hash and cannot be decrypted"
        )
    try:
        return cisco_type7.decrypt(token)
    except ValueError as exc:
        # The library echoes the offending token in some messages; a type 7 value
        # is trivially reversible, so keep it out of errors and logs.
        raise CiscoSecretError("malformed Cisco type 7 value") from exc
