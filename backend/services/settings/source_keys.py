from __future__ import annotations

import re
from typing import Literal

SourceType = Literal["nautobot", "git"]

SOURCE_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
NAUTOBOT_KEY_PREFIX = "sources.nautobot."
GIT_KEY_PREFIX = "sources.git."


def build_source_key(source_type: SourceType, source_id: str) -> str:
    normalized = source_id.strip().lower()
    if not SOURCE_ID_PATTERN.fullmatch(normalized):
        raise ValueError(
            "Source ID must start with a letter and contain only lowercase "
            "letters, numbers, underscores, and hyphens (max 64 characters).",
        )
    prefix = NAUTOBOT_KEY_PREFIX if source_type == "nautobot" else GIT_KEY_PREFIX
    return f"{prefix}{normalized}"


def parse_source_key(key: str) -> tuple[SourceType, str] | None:
    if key.startswith(NAUTOBOT_KEY_PREFIX):
        source_id = key[len(NAUTOBOT_KEY_PREFIX) :]
    elif key.startswith(GIT_KEY_PREFIX):
        source_id = key[len(GIT_KEY_PREFIX) :]
    else:
        return None

    if not source_id or not SOURCE_ID_PATTERN.fullmatch(source_id):
        return None

    source_type: SourceType = "nautobot" if key.startswith(NAUTOBOT_KEY_PREFIX) else "git"
    return source_type, source_id


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
