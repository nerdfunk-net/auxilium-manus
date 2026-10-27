"""Database-backed glossary lookup for the assistant tools (a short-lived session in a thread)."""

from __future__ import annotations

import asyncio
from typing import Any

from core.database import SessionLocal
from services.ai_assistant.glossary_service import GlossaryService


class DbGlossaryReader:
    """Entries of one kind whose term or alias is exactly the word asked for."""

    def __init__(self, kind: str) -> None:
        self._kind = kind

    async def lookup(self, term: str) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._lookup, term)

    async def suggest(self, term: str) -> list[str]:
        return await asyncio.to_thread(self._suggest, term)

    def _suggest(self, term: str) -> list[str]:
        with SessionLocal() as db:
            return GlossaryService(db).suggest(self._kind, term)

    def _lookup(self, term: str) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            return GlossaryService(db).lookup(self._kind, term)
