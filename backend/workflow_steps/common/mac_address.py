"""MAC address normalisation shared by the steps that fill the client data tables."""

from __future__ import annotations

import re

_MAC_SEPARATORS = re.compile(r"[.:\-]")
_HEX_12 = re.compile(r"^[0-9a-f]{12}$")


def normalise_mac(raw: str | None) -> str | None:
    """Return ``aabb.ccdd.eeff`` for any common MAC notation, or ``None`` if not a MAC."""
    if not raw:
        return None
    digits = _MAC_SEPARATORS.sub("", raw.strip()).lower()
    if not _HEX_12.match(digits):
        return None
    return f"{digits[0:4]}.{digits[4:8]}.{digits[8:12]}"
