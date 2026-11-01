"""What every query needs: a Nautobot client and the cached vocabularies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from nautobot_read.vocabularies import VocabularyCache


@dataclass(frozen=True)
class QueryContext:
    client: Any  # a GraphQLClient (or a test double with the same methods)
    vocabularies: VocabularyCache
