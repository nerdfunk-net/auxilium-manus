"""Name schema for interface redundancy groups, e.g. ``hsrp-{next}`` -> ``hsrp-1``, ``hsrp-2``.

Pure functions. ``{next}`` is the lowest free positive integer among the existing group names;
``{protocol}`` is the group's protocol in lower case (``hsrp``). Everything else is literal.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

DEFAULT_NAME_PATTERN = "hsrp-{next}"
NEXT = "{next}"
PROTOCOL = "{protocol}"
_MAX_NAME = 255


def validate_name_pattern(pattern: object) -> str | None:
    """A message when ``pattern`` is unusable, else ``None``."""
    if not isinstance(pattern, str) or not pattern.strip():
        return "name pattern must be a non-empty text"
    if pattern.count(NEXT) != 1:
        return f"name pattern must contain {NEXT} exactly once"
    literal = pattern.replace(NEXT, "").replace(PROTOCOL, "")
    if "{" in literal or "}" in literal:
        return f"name pattern may only use {NEXT} and {PROTOCOL}"
    if "/" in pattern or any(ord(char) < 32 for char in pattern):
        return "name pattern must not contain '/' or control characters"
    if len(pattern) > _MAX_NAME - 6:
        return "name pattern is too long"
    return None


def literal_prefix(pattern: str, protocol: str) -> str:
    """Fixed text before ``{next}`` (``hsrp-`` for ``hsrp-{next}``); narrows the name lookup."""
    return pattern.replace(PROTOCOL, protocol.lower()).split(NEXT, 1)[0]


def _name_regex(pattern: str, protocol: str) -> re.Pattern[str]:
    resolved = pattern.replace(PROTOCOL, protocol.lower())
    before, after = resolved.split(NEXT, 1)
    return re.compile(rf"^{re.escape(before)}([1-9]\d*){re.escape(after)}$")


def next_free_name(pattern: str, protocol: str, existing_names: Iterable[str]) -> str:
    """``pattern`` with ``{next}`` set to the lowest positive integer no existing name uses."""
    regex = _name_regex(pattern, protocol)
    taken = {int(match.group(1)) for name in existing_names if (match := regex.match(name))}
    number = 1
    while number in taken:
        number += 1
    return pattern.replace(PROTOCOL, protocol.lower()).replace(NEXT, str(number))
