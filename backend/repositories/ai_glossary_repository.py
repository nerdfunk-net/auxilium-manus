from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.domain_exceptions import ConflictError
from core.models.ai_glossary import AiGlossaryName, AiGlossaryTerm
from repositories.updates import apply_updates

_UPDATABLE_FIELDS = frozenset({"term", "term_key", "aliases", "search_text", "payload", "note"})
_NAME_TAKEN = "That term or one of its aliases is already used by another glossary term"


def _escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


class AiGlossaryRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def count(self, kind: str, query: str | None = None) -> int:
        stmt = select(func.count()).select_from(AiGlossaryTerm).where(AiGlossaryTerm.kind == kind)
        return self.db.scalar(self._filtered(stmt, query)) or 0

    def search(self, kind: str, query: str | None, limit: int, offset: int) -> list[AiGlossaryTerm]:
        stmt = self._filtered(select(AiGlossaryTerm).where(AiGlossaryTerm.kind == kind), query)
        stmt = stmt.order_by(AiGlossaryTerm.term_key).limit(limit).offset(offset)
        return list(self.db.scalars(stmt))

    def get(self, term_id: int) -> AiGlossaryTerm | None:
        return self.db.get(AiGlossaryTerm, term_id)

    def names_in_use(self, kind: str, keys: Sequence[str], own_id: int | None) -> list[str]:
        """Which of ``keys`` another entry of the same kind already uses."""
        stmt = select(AiGlossaryName.name_key).where(
            AiGlossaryName.kind == kind, AiGlossaryName.name_key.in_(list(keys))
        )
        if own_id is not None:
            stmt = stmt.where(AiGlossaryName.term_id != own_id)
        return sorted(self.db.scalars(stmt))

    def names_of_kind(self, kind: str) -> list[str]:
        """Every folded term and alias of ``kind`` (for "did you mean")."""
        stmt = select(AiGlossaryName.name_key).where(AiGlossaryName.kind == kind)
        return sorted(self.db.scalars(stmt))

    def find_by_name(self, kind: str, key: str) -> list[AiGlossaryTerm]:
        """The entry of ``kind`` whose term or alias is exactly ``key`` (already folded)."""
        stmt = (
            select(AiGlossaryTerm)
            .join(AiGlossaryName, AiGlossaryName.term_id == AiGlossaryTerm.id)
            .where(AiGlossaryName.kind == kind, AiGlossaryName.name_key == key)
        )
        return list(self.db.scalars(stmt))

    def create(
        self, values: Mapping[str, Any], names: Sequence[str], created_by_id: int | None
    ) -> AiGlossaryTerm:
        row = AiGlossaryTerm(created_by_id=created_by_id, **values)
        try:
            self.db.add(row)
            self.db.flush()
            self.db.add_all(
                AiGlossaryName(term_id=row.id, kind=row.kind, name_key=n) for n in names
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError(_NAME_TAKEN) from exc
        self.db.refresh(row)
        return row

    def update(
        self, row: AiGlossaryTerm, values: Mapping[str, Any], names: Sequence[str]
    ) -> AiGlossaryTerm:
        try:
            apply_updates(row, values, _UPDATABLE_FIELDS)
            self.db.execute(delete(AiGlossaryName).where(AiGlossaryName.term_id == row.id))
            self.db.flush()
            self.db.add_all(
                AiGlossaryName(term_id=row.id, kind=row.kind, name_key=n) for n in names
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            raise ConflictError(_NAME_TAKEN) from exc
        self.db.refresh(row)
        return row

    def delete(self, row: AiGlossaryTerm) -> None:
        self.db.execute(delete(AiGlossaryName).where(AiGlossaryName.term_id == row.id))
        self.db.delete(row)
        self.db.commit()

    @staticmethod
    def _filtered(stmt: Any, query: str | None) -> Any:
        text = (query or "").strip().lower()
        if not text:
            return stmt
        return stmt.where(AiGlossaryTerm.search_text.like(f"%{_escape_like(text)}%", escape="\\"))
