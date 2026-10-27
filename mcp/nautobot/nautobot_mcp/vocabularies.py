"""Loading and caching the name vocabularies of one Nautobot instance.

Plain name lists (roles, statuses, tags, ...) become a ``Vocabulary``. Locations get a
``LocationDirectory`` instead, because location names are not unique across parents.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from nautobot_mcp.vocabulary import UUID_PATTERN, Vocabulary

DEFAULT_TTL_SECONDS = 300.0
PATH_SEPARATOR = " → "
_PATH_SPLIT = re.compile(r"\s*[→>]\s*")
_LOCATION_SELECTION = "id name location_type { name } parent { id }"


class AmbiguousNameError(ValueError):
    """A name matches several objects; the message lists them for the calling LLM."""


class _Lister(Protocol):
    async def list_all(
        self, root: str, selection: str, filters: Mapping[str, Sequence[str] | None] | None = None
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class LocationRecord:
    id: str
    name: str
    path: str
    location_type: str


class LocationDirectory:
    """All locations, resolvable by name, full path (``Germany → Berlin``) or UUID."""

    def __init__(self, records: tuple[LocationRecord, ...]) -> None:
        self.records = records
        self.names: tuple[str, ...] = tuple(dict.fromkeys(r.name for r in records))
        self._by_id = {r.id.lower(): r for r in records}
        self._by_path = {_fold_path(r.path): r for r in records}
        self._by_name: dict[str, list[LocationRecord]] = {}
        for record in records:
            self._by_name.setdefault(record.name.casefold(), []).append(record)

    @classmethod
    def from_rows(cls, rows: list[dict[str, Any]]) -> LocationDirectory:
        by_id = {row["id"]: row for row in rows}
        records = tuple(
            LocationRecord(
                id=row["id"],
                name=row["name"],
                path=PATH_SEPARATOR.join(_ancestry(row, by_id)),
                location_type=(row.get("location_type") or {}).get("name", ""),
            )
            for row in rows
        )
        return cls(records)

    def path_of(self, location_id: str) -> str:
        """The full path of a known location id, or an empty string."""
        record = self._by_id.get(location_id.lower())
        return record.path if record else ""

    def resolve(self, value: str) -> LocationRecord:
        text = value.strip()
        if UUID_PATTERN.match(text) and text.lower() in self._by_id:
            return self._by_id[text.lower()]
        if _PATH_SPLIT.search(text):
            record = self._by_path.get(_fold_path(text))
            if record is not None:
                return record
        else:
            matches = self._by_name.get(text.casefold(), [])
            if len(matches) == 1:
                return matches[0]
            if matches:
                raise AmbiguousNameError(self._ambiguous_message(text, matches))
        raise Vocabulary("location", self.names).miss(text)

    @staticmethod
    def _ambiguous_message(text: str, matches: list[LocationRecord]) -> str:
        listing = "; ".join(f"{m.path} ({m.location_type}, id {m.id})" for m in matches)
        return (
            f"'{text}' matches {len(matches)} locations: {listing}. "
            "Retry with the full path (for example 'Parent → Name') or the id."
        )


def _ancestry(row: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> list[str]:
    names = [row["name"]]
    seen = {row["id"]}
    parent_id = (row.get("parent") or {}).get("id")
    while parent_id and parent_id in by_id and parent_id not in seen:
        seen.add(parent_id)
        names.append(by_id[parent_id]["name"])
        parent_id = (by_id[parent_id].get("parent") or {}).get("id")
    return list(reversed(names))


def _fold_path(path: str) -> str:
    return PATH_SEPARATOR.join(part.casefold() for part in _PATH_SPLIT.split(path.strip()))


@dataclass(frozen=True)
class VocabSpec:
    """How to load one vocabulary: GraphQL root, the field holding the name, and filters."""

    kind: str
    root: str
    field: str = "name"
    filters: tuple[tuple[str, tuple[str, ...]], ...] = ()


def roles_spec(content_type: str) -> VocabSpec:
    return VocabSpec(f"{content_type} role", "roles", filters=(("content_types", (content_type,)),))


def statuses_spec(content_type: str) -> VocabSpec:
    return VocabSpec(
        f"{content_type} status", "statuses", filters=(("content_types", (content_type,)),)
    )


def tags_spec(content_type: str) -> VocabSpec:
    return VocabSpec(f"{content_type} tag", "tags", filters=(("content_types", (content_type,)),))


LOCATION_TYPES_SPEC = VocabSpec("location type", "location_types")
DEVICE_TYPES_SPEC = VocabSpec("device type", "device_types", field="model")
PLATFORMS_SPEC = VocabSpec("platform", "platforms")
NAMESPACES_SPEC = VocabSpec("namespace", "namespaces")


class VocabularyCache:
    """Loads vocabularies on demand and keeps them for ``ttl_seconds``."""

    def __init__(
        self,
        client: _Lister,
        *,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._clock = clock
        self._entries: dict[object, tuple[float, Any]] = {}

    def invalidate(self) -> None:
        self._entries.clear()

    async def get(self, spec: VocabSpec) -> Vocabulary:
        cached = self._fresh(spec)
        if cached is not None:
            return cached
        filters = {name: list(values) for name, values in spec.filters}
        rows = await self._client.list_all(spec.root, spec.field, filters or None)
        vocabulary = Vocabulary(spec.kind, (row[spec.field] for row in rows))
        self._entries[spec] = (self._clock(), vocabulary)
        return vocabulary

    async def locations(self) -> LocationDirectory:
        cached = self._fresh("locations")
        if cached is not None:
            return cached
        rows = await self._client.list_all("locations", _LOCATION_SELECTION)
        directory = LocationDirectory.from_rows(rows)
        self._entries["locations"] = (self._clock(), directory)
        return directory

    def _fresh(self, key: object) -> Any | None:
        entry = self._entries.get(key)
        if entry is None or self._clock() - entry[0] >= self._ttl:
            return None
        return entry[1]
