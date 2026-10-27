"""What every tool needs: the Nautobot client and the cached vocabularies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nautobot_mcp.vocabularies import VocabularyCache


@dataclass(frozen=True)
class AppContext:
    client: Any  # NautobotClient (or a test double with the same methods)
    vocabularies: VocabularyCache
