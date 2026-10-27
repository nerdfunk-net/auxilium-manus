"""Name vocabularies (roles, statuses, locations, ...) and tolerant name resolution.

Nautobot fails a whole query when any filter value is not a known name, so every name a
tool receives is resolved here first. A miss raises an error that tells the LLM what to
retry with instead of silently returning nothing.
"""

from __future__ import annotations

import difflib
import re
from collections.abc import Iterable

MAX_LISTED_NAMES = 20
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


class UnknownNameError(ValueError):
    """A value is not in the vocabulary; the message is written for the calling LLM."""


class Vocabulary:
    """The known names of one kind (for example the device roles of this instance)."""

    def __init__(self, kind: str, names: Iterable[str], *, allow_uuid: bool = False) -> None:
        self.kind = kind
        self.names: tuple[str, ...] = tuple(dict.fromkeys(names))
        self._allow_uuid = allow_uuid
        self._by_folded = {_fold(name): name for name in self.names}

    def resolve(self, value: str) -> str:
        """Return the canonical name for ``value`` (case and surrounding space ignored)."""
        if self._allow_uuid and UUID_PATTERN.match(value.strip()):
            return value.strip()
        canonical = self._by_folded.get(_fold(value))
        if canonical is None:
            raise self.miss(value)
        return canonical

    def resolve_many(self, values: Iterable[str]) -> tuple[str, ...]:
        return tuple(self.resolve(value) for value in values)

    def miss(self, value: str) -> UnknownNameError:
        """The error for a value that is not in this vocabulary (closest + available names)."""
        return UnknownNameError(self._message(value))

    def _message(self, value: str) -> str:
        parts = [f"No {self.kind} '{value}'."]
        if not self.names:
            return f"{parts[0]} None exist in this Nautobot."
        close = difflib.get_close_matches(_fold(value), list(self._by_folded), n=1, cutoff=0.6)
        if close:
            parts.append(f"Closest: '{self._by_folded[close[0]]}'.")
        listed = ", ".join(self.names[:MAX_LISTED_NAMES])
        hidden = len(self.names) - MAX_LISTED_NAMES
        parts.append(f"Available: {listed}" + (f" and {hidden} more." if hidden > 0 else "."))
        return " ".join(parts)


def _fold(value: str) -> str:
    return value.strip().casefold()
