"""Durable artifact export sinks (filesystem, git, object store, …)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StoredExport:
    """Metadata for a file written by store-artifact."""

    destination: str
    path: str
    size_bytes: int
    sha256: str | None = None


class ArtifactSink(ABC):
    """Write workflow content to a durable destination outside run-scoped storage."""

    @property
    @abstractmethod
    def destination(self) -> str:
        """Sink identifier (e.g. ``filesystem``, ``git``)."""

    @abstractmethod
    async def write_text(
        self,
        *,
        relative_path: str,
        content: str,
        workflow_id: str,
        run_id: str,
    ) -> StoredExport:
        """Persist text content and return export metadata."""
