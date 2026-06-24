"""Artifact storage for workflow step content (configs, command output)."""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Union
from uuid import uuid4

from models.workflow_context import ArtifactRef

ContentType = Union[str, bytes]


class ArtifactService(ABC):
    """Store and resolve bulky workflow content outside the envelope."""

    @abstractmethod
    async def store(
        self,
        *,
        content: ContentType,
        kind: str,
        device_id: str,
        run_id: str,
        media_type: str = "text/plain",
    ) -> ArtifactRef:
        """Persist content and return a reference for the envelope."""

    @abstractmethod
    async def resolve(self, ref: ArtifactRef) -> str:
        """Load stored content as text."""


class InMemoryArtifactService(ArtifactService):
    """Ephemeral artifact backend for development and unit tests."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def store(
        self,
        *,
        content: ContentType,
        kind: str,
        device_id: str,
        run_id: str,
        media_type: str = "text/plain",
    ) -> ArtifactRef:
        text = content.decode("utf-8") if isinstance(content, bytes) else content
        artifact_id = str(uuid4())
        self._store[artifact_id] = text
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return ArtifactRef(
            artifact_id=artifact_id,
            kind=kind,
            media_type=media_type,
            size_bytes=len(text.encode("utf-8")),
            sha256=digest,
        )

    async def resolve(self, ref: ArtifactRef) -> str:
        try:
            return self._store[ref.artifact_id]
        except KeyError as exc:
            raise RuntimeError(f"Artifact not found: {ref.artifact_id}") from exc
