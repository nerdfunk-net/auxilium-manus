from __future__ import annotations

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from core.models.templates import Template


class TemplatesRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_id(self, template_id: int) -> Template | None:
        return self.db.scalar(select(Template).where(Template.id == template_id))

    def get_active_by_name(self, name: str) -> Template | None:
        return self.db.scalar(
            select(Template).where(
                Template.name == name,
                Template.is_active.is_(True),
            )
        )

    def list_templates(
        self,
        *,
        category: str | None = None,
        search: str | None = None,
        active_only: bool = True,
    ) -> list[Template]:
        stmt = select(Template)
        if active_only:
            stmt = stmt.where(Template.is_active.is_(True))
        if category:
            stmt = stmt.where(Template.category == category)
        if search:
            needle = f"%{search.lower()}%"
            stmt = stmt.where(func.lower(Template.name).like(needle))
        stmt = stmt.order_by(Template.name.asc())
        return list(self.db.scalars(stmt))

    def list_categories(self) -> list[str]:
        stmt = (
            select(distinct(Template.category))
            .where(Template.is_active.is_(True))
            .order_by(Template.category.asc())
        )
        return [row for row in self.db.scalars(stmt) if row]

    def create(self, **kwargs) -> Template:
        template = Template(**kwargs)
        self.db.add(template)
        self.db.commit()
        self.db.refresh(template)
        return template

    def update(self, template: Template, **kwargs) -> Template:
        for key, value in kwargs.items():
            setattr(template, key, value)
        self.db.commit()
        self.db.refresh(template)
        return template

    def delete(self, template: Template) -> None:
        self.db.delete(template)
        self.db.commit()
