"""Random secret generation policies for the ``secret-generate`` workflow step.

Named presets rather than free-form regex, so the step's config panel can
offer a fixed dropdown instead of asking an operator to write a charset.
Uses the stdlib ``secrets`` module (cryptographically secure), never
``random``.
"""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass
from enum import StrEnum

MIN_LENGTH = 4
MAX_LENGTH = 256


class SecretCharset(StrEnum):
    HEX = "hex"  # TACACS+ shared secrets, generic tokens
    ALNUM = "alnum"  # SNMP community strings — avoid symbols some NMS choke on
    ALNUM_SYMBOLS = "alnum_symbols"  # SNMPv3 auth/priv passphrases


_ALPHABETS: dict[SecretCharset, str] = {
    SecretCharset.ALNUM: string.ascii_letters + string.digits,
    SecretCharset.ALNUM_SYMBOLS: string.ascii_letters + string.digits + "!@#$%^&*()-_=+",
}


@dataclass(frozen=True)
class SecretGenerationPolicy:
    charset: SecretCharset = SecretCharset.HEX
    length: int = 32

    def __post_init__(self) -> None:
        if not MIN_LENGTH <= self.length <= MAX_LENGTH:
            raise ValueError(
                f"secret generation length must be between {MIN_LENGTH} and {MAX_LENGTH}"
            )


def generate_secret(policy: SecretGenerationPolicy) -> str:
    """Generate a random secret value per *policy*."""
    if policy.charset == SecretCharset.HEX:
        # token_hex(n) returns 2n hex characters; halve so `length` is the
        # actual output length (rounding down for an odd length).
        return secrets.token_hex((policy.length + 1) // 2)[: policy.length]

    alphabet = _ALPHABETS[policy.charset]
    return "".join(secrets.choice(alphabet) for _ in range(policy.length))
