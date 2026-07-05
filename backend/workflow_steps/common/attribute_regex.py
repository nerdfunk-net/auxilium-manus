"""Regular-expression transforms for workflow attribute updates."""

from __future__ import annotations

import re
from typing import Any


class RegexFlagsConfig(dict[str, bool]):
    """Normalized regex flag mapping from step config or API requests."""

    @classmethod
    def from_mapping(cls, raw: Any) -> RegexFlagsConfig:
        if not isinstance(raw, dict):
            return cls(
                case_insensitive=False,
                multiline=False,
                dotall=False,
            )
        return cls(
            case_insensitive=_coerce_bool(raw.get("case_insensitive")),
            multiline=_coerce_bool(raw.get("multiline")),
            dotall=_coerce_bool(raw.get("dotall")),
        )


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def compile_regex_flags(flags: RegexFlagsConfig | dict[str, bool]) -> int:
    """Build a Python ``re`` flags bitmask from user-facing toggles."""
    normalized = (
        flags
        if isinstance(flags, RegexFlagsConfig)
        else RegexFlagsConfig.from_mapping(flags)
    )
    compiled = 0
    if normalized.get("case_insensitive"):
        compiled |= re.IGNORECASE
    if normalized.get("multiline"):
        compiled |= re.MULTILINE
    if normalized.get("dotall"):
        compiled |= re.DOTALL
    return compiled


def compile_pattern(pattern: str, flags: RegexFlagsConfig | dict[str, bool]) -> re.Pattern[str]:
    """Compile *pattern* or raise ``ValueError`` with a user-safe message."""
    try:
        return re.compile(pattern, compile_regex_flags(flags))
    except re.error as exc:
        raise ValueError(f"invalid regular expression: {exc}") from exc


def probe_regex_transform(
    *,
    source_text: str,
    pattern: str,
    destination_template: str,
    flags: RegexFlagsConfig | dict[str, bool] | None = None,
) -> dict[str, Any]:
    """Return match metadata and the expanded destination value for UI probing."""
    normalized_flags = RegexFlagsConfig.from_mapping(flags or {})
    compiled = compile_pattern(pattern, normalized_flags)
    match = compiled.search(source_text)
    if match is None:
        return {
            "matched": False,
            "source_text": source_text,
            "full_match": None,
            "groups": {},
            "named_groups": {},
            "destination_value": None,
        }

    groups = {
        str(index): group
        for index, group in enumerate(match.groups(), start=1)
        if group is not None
    }
    named_groups = {
        name: value for name, value in match.groupdict().items() if value is not None
    }
    destination_value = match.expand(destination_template)

    return {
        "matched": True,
        "source_text": source_text,
        "full_match": match.group(0),
        "groups": groups,
        "named_groups": named_groups,
        "destination_value": destination_value,
    }


def apply_regex_transform(
    *,
    source_text: str,
    pattern: str,
    destination_template: str,
    flags: RegexFlagsConfig | dict[str, bool] | None = None,
) -> str | None:
    """Apply the first regex match or return ``None`` when there is no match."""
    result = probe_regex_transform(
        source_text=source_text,
        pattern=pattern,
        destination_template=destination_template,
        flags=flags,
    )
    if not result["matched"]:
        return None
    return str(result["destination_value"])
