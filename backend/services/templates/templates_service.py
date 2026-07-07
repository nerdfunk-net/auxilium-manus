"""Business logic for Netmiko Jinja2 templates: CRUD + Jinja2 rendering."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from jinja2 import Template as JinjaTemplate
from jinja2 import TemplateError
from jinja2.exceptions import UndefinedError
from sqlalchemy.orm import Session

from core.models.templates import Template
from repositories.templates_repository import TemplatesRepository
from services.templates.exceptions import (
    TemplateNameConflictError,
    TemplateNotFoundError,
)

logger = logging.getLogger(__name__)

_VARIABLE_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_.]*)")


class TemplatesService:
    def __init__(self, db: Session) -> None:
        self._repo = TemplatesRepository(db)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def list_templates(
        self,
        *,
        category: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        templates = self._repo.list_templates(category=category, search=search)
        return [self._to_dict(template) for template in templates]

    def list_categories(self) -> list[str]:
        return self._repo.list_categories()

    def get_template(self, template_id: int) -> dict[str, Any]:
        template = self._repo.get_by_id(template_id)
        if template is None or not template.is_active:
            raise TemplateNotFoundError(template_id)
        return self._to_dict(template)

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def create_template(
        self,
        *,
        name: str,
        description: str | None,
        template_type: str,
        category: str,
        content: str,
        variables: dict[str, Any],
        pre_run_command: str | None,
        credential_id: int | None,
        created_by: str | None,
    ) -> dict[str, Any]:
        if self._repo.get_active_by_name(name) is not None:
            raise TemplateNameConflictError(name)

        template = self._repo.create(
            name=name,
            source="webeditor",
            template_type=template_type,
            category=category,
            description=description,
            content=content,
            variables=json.dumps(variables),
            pre_run_command=pre_run_command,
            credential_id=credential_id,
            created_by=created_by,
            is_active=True,
        )
        logger.info("Template '%s' created with ID %s", name, template.id)
        return self._to_dict(template)

    def update_template(
        self,
        template_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        template_type: str | None = None,
        category: str | None = None,
        content: str | None = None,
        variables: dict[str, Any] | None = None,
        pre_run_command: str | None = None,
        credential_id: int | None = None,
    ) -> dict[str, Any]:
        template = self._repo.get_by_id(template_id)
        if template is None or not template.is_active:
            raise TemplateNotFoundError(template_id)

        if name is not None and name != template.name:
            conflict = self._repo.get_active_by_name(name)
            if conflict is not None and conflict.id != template_id:
                raise TemplateNameConflictError(name)

        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if description is not None:
            updates["description"] = description
        if template_type is not None:
            updates["template_type"] = template_type
        if category is not None:
            updates["category"] = category
        if content is not None:
            updates["content"] = content
        if variables is not None:
            updates["variables"] = json.dumps(variables)
        if pre_run_command is not None:
            updates["pre_run_command"] = pre_run_command
        if credential_id is not None:
            updates["credential_id"] = credential_id

        updated = self._repo.update(template, **updates)
        logger.info("Template %s updated", template_id)
        return self._to_dict(updated)

    def delete_template(self, template_id: int, *, hard_delete: bool = False) -> None:
        template = self._repo.get_by_id(template_id)
        if template is None:
            raise TemplateNotFoundError(template_id)
        if hard_delete:
            self._repo.delete(template)
        else:
            self._repo.update(template, is_active=False)
        logger.info(
            "Template %s %s", template_id, "deleted" if hard_delete else "deactivated"
        )

    # ------------------------------------------------------------------
    # Render
    # ------------------------------------------------------------------

    def render(self, *, template_content: str, variables: dict[str, Any]) -> dict[str, Any]:
        """Render Jinja2 ``template_content`` with the provided ``variables``."""
        variables_used = sorted(set(_VARIABLE_PATTERN.findall(template_content)))
        try:
            rendered = JinjaTemplate(template_content).render(**variables)
        except UndefinedError as exc:
            available = ", ".join(sorted(variables.keys())) or "none"
            raise ValueError(
                f"Undefined variable in template: {exc}. Available variables: {available}"
            ) from exc
        except TemplateError as exc:
            raise ValueError(f"Template syntax error: {exc}") from exc

        return {
            "rendered_content": rendered,
            "variables_used": variables_used,
            "warnings": [],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _to_dict(self, template: Template) -> dict[str, Any]:
        try:
            variables = json.loads(template.variables) if template.variables else {}
        except json.JSONDecodeError:
            variables = {}

        return {
            "id": template.id,
            "name": template.name,
            "source": template.source,
            "template_type": template.template_type,
            "category": template.category,
            "description": template.description,
            "content": template.content,
            "variables": variables,
            "pre_run_command": template.pre_run_command,
            "credential_id": template.credential_id,
            "created_by": template.created_by,
            "is_active": template.is_active,
            "created_at": template.created_at.isoformat() if template.created_at else None,
            "updated_at": template.updated_at.isoformat() if template.updated_at else None,
        }
