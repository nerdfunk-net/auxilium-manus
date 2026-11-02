"""Matching device names between Nautobot / the user and Batfish (doc/AI_TOOL_CHAIN.md §33).

Batfish names a node after the hostname in the device config: lower case, and usually without a
domain (``lab``). Nautobot names the same device by its FQDN (``LAB.local.zz``). A name the user
or a Nautobot answer supplies therefore rarely equals a Batfish node name.

Two names are the *same device* when they are equal ignoring case, or when one is the other
followed by a domain (``lab`` and ``lab.local.zz``). Two names with different domains
(``lab.a.zz`` and ``lab.b.zz``) are different devices. A name that fits several nodes is reported
as ambiguous; it is never guessed.

Pure functions plus a small expiring cache for the node list of a snapshot. No I/O.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from difflib import SequenceMatcher

MAX_SUGGESTIONS = 5
# How alike two first labels must be to count as a typo of each other (``sw-egde`` / ``sw-edge``).
_TYPO_RATIO = 0.8


@dataclass(frozen=True)
class NodeResolution:
    """Outcome of matching requested names against the nodes of one snapshot."""

    resolved: dict[str, str] = field(default_factory=dict)
    # requested name -> close node names (possibly none)
    unknown: dict[str, tuple[str, ...]] = field(default_factory=dict)
    # requested name -> every node it could mean
    ambiguous: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def changed(self) -> dict[str, str]:
        """The names that were rewritten (a name that already was the node name is left out)."""
        return {name: node for name, node in self.resolved.items() if name != node}


def _same_device(a: str, b: str) -> bool:
    """``a`` and ``b`` (both case-folded) are equal or differ only by a trailing domain."""
    return a == b or a.startswith(b + ".") or b.startswith(a + ".")


def _first_label(name: str) -> str:
    return name.split(".", 1)[0]


def _suggestions(wanted: str, known: Sequence[str]) -> tuple[str, ...]:
    """Nodes whose first label starts with the one asked for, or is a near miss of it.

    Not a substring search: ``core`` is not close to ``sw-core``. These are candidates to put to
    the user, never names to retry with.
    """
    label = _first_label(wanted)
    if not label:
        return ()
    close = sorted(
        node
        for node in known
        if _first_label(node.casefold()).startswith(label)
        or SequenceMatcher(None, label, _first_label(node.casefold())).ratio() >= _TYPO_RATIO
    )
    return tuple(close[:MAX_SUGGESTIONS])


def resolve_node_names(requested: Sequence[str], known: Sequence[str]) -> NodeResolution:
    """Match each requested name to a node of ``known`` (the node names of one snapshot)."""
    resolved: dict[str, str] = {}
    unknown: dict[str, tuple[str, ...]] = {}
    ambiguous: dict[str, tuple[str, ...]] = {}
    folded = [(node, node.casefold()) for node in known]
    for name in requested:
        wanted = name.strip().casefold()
        exact = [node for node, key in folded if key == wanted]
        matches = exact or [node for node, key in folded if _same_device(wanted, key)]
        if len(matches) == 1:
            resolved[name] = matches[0]
        elif matches:
            ambiguous[name] = tuple(sorted(matches))
        elif known:
            unknown[name] = _suggestions(wanted, known)
    return NodeResolution(resolved=resolved, unknown=unknown, ambiguous=ambiguous)


CacheKey = tuple[str, int, str, str]


class NodeNameCache:
    """Node names per (host, port, network, snapshot), kept for ``ttl_seconds``.

    A snapshot does not change, but it can be re-created under the same name, so entries expire.
    The oldest entry goes when the cache is full.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 300.0,
        max_entries: int = 64,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_seconds
        self._max = max_entries
        self._clock = clock
        self._entries: dict[CacheKey, tuple[float, tuple[str, ...]]] = {}

    def get(self, key: CacheKey) -> tuple[str, ...] | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        stored_at, names = entry
        if self._clock() - stored_at > self._ttl:
            del self._entries[key]
            return None
        return names

    def put(self, key: CacheKey, names: tuple[str, ...]) -> None:
        if key not in self._entries and len(self._entries) >= self._max:
            oldest = min(self._entries, key=lambda k: self._entries[k][0])
            del self._entries[oldest]
        self._entries[key] = (self._clock(), names)

    def clear(self) -> None:
        self._entries.clear()
