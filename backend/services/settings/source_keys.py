from __future__ import annotations

import re
from typing import Literal

SourceType = Literal["nautobot", "git", "ise"]

SOURCE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
NAUTOBOT_KEY_PREFIX = "sources.nautobot."
GIT_KEY_PREFIX = "sources.git."
ISE_KEY_PREFIX = "sources.ise."

_PREFIX_BY_TYPE: dict[SourceType, str] = {
    "nautobot": NAUTOBOT_KEY_PREFIX,
    "git": GIT_KEY_PREFIX,
    "ise": ISE_KEY_PREFIX,
}
_TYPE_BY_PREFIX: dict[str, SourceType] = {
    prefix: source_type for source_type, prefix in _PREFIX_BY_TYPE.items()
}


def build_source_key(source_type: SourceType, source_id: str) -> str:
    normalized = source_id.strip().lower()
    if not SOURCE_ID_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Source ID must start with a letter and contain only lowercase "
            "letters, numbers, underscores, and hyphens (max 64 characters).",
        )
    return f"{_PREFIX_BY_TYPE[source_type]}{normalized}"


def parse_source_key(key: str) -> tuple[SourceType, str] | None:
    for prefix, source_type in _TYPE_BY_PREFIX.items():
        if not key.startswith(prefix):
            continue
        source_id = key[len(prefix) :]
        if not source_id or not SOURCE_ID_PATTERN.fullmatch(source_id):
            return None
        return source_type, source_id
    return None


def ensure_value_source_id(
    value: dict,
    *,
    source_type: SourceType,
    source_id: str,
) -> dict:
    """Persist source_id inside JSON for API consumers and workflow step references."""
    return {
        **value,
        "source_id": source_id,
        "source_type": source_type,
    }
