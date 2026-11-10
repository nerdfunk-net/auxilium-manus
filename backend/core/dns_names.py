"""DNS name syntax shared by startup configuration and the Ask the Net DNS tool.

Kept in ``core`` so ``core.config`` can validate ``AI_DNS_ALLOWED_SUFFIXES`` at startup without
importing the assistant package. Pure functions.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

MAX_NAME_LENGTH = 253
_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def is_valid_dns_name(name: str) -> bool:
    """A lower-case name of letter-digit-hyphen labels, without a trailing dot."""
    if not name or len(name) > MAX_NAME_LENGTH:
        return False
    return all(_LABEL.fullmatch(label) for label in name.split("."))


def normalize_suffix(raw: str) -> str:
    """A configured suffix in canonical form, or ``ValueError`` (startup refuses it)."""
    suffix = raw.strip().strip(".").lower()
    if not is_valid_dns_name(suffix):
        raise ValueError(f"AI_DNS_ALLOWED_SUFFIXES: {raw!r} is not a valid DNS suffix")
    if "." not in suffix:
        # One label ("com") would allow a whole TLD and defeat the exfiltration limit.
        raise ValueError(f"AI_DNS_ALLOWED_SUFFIXES: {raw!r} needs at least two labels")
    return suffix


def normalize_suffixes(raw: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({normalize_suffix(item) for item in raw}))
