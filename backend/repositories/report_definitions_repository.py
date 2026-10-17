from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.models.report_definitions import ReportDefinition
from repositories.updates import apply_updates

_UPDATABLE_FIELDS = frozenset(
    {"name", "description", "sections", "template_id", "default_recipients"}
)


class ReportDefinitionsRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get(self, definition_id: int) -> ReportDefinition | None:
        return self.db.get(ReportDefinition, definition_id)

    def get_by_name(self, name: str) -> ReportDefinition | None:
        return self.db.scalar(select(ReportDefinition).where(ReportDefinition.name == name))

    def list_all(self) -> list[ReportDefinition]:
        return list(self.db.scalars(select(ReportDefinition).order_by(ReportDefinition.name)))

    def create(self, **kwargs) -> ReportDefinition:
        definition = ReportDefinition(**kwargs)
        self.db.add(definition)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(definition)
        return definition

    def update(self, definition: ReportDefinition, **kwargs) -> ReportDefinition:
        apply_updates(definition, kwargs, _UPDATABLE_FIELDS)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(definition)
        return definition

    def delete(self, definition: ReportDefinition) -> None:
        self.db.delete(definition)
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
