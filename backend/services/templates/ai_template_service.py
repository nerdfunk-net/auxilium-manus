"""The ai-assistant's template write path (create a draft, edit its own drafts).

Unlike workflows there is no per-item consent row for templates, and templates are executed by
live workflows (Jinja rendering unwraps sealed secrets). The AI is therefore confined to its own
drafts: it may create templates whose name starts with ``AI_DRAFT_PREFIX`` and update only
templates it created. A human promotes a draft by renaming it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from core.domain_exceptions import AccessDeniedError
from core.models.users import User
from models.templates import TemplateCreate, TemplateUpdate
from repositories.templates_repository import TemplatesRepository
from repositories.user_repository import UserRepository
from services.auth.rbac_seed import AI_ASSISTANT_USERNAME
from services.templates.exceptions import TemplateNotFoundError
from services.templates.templates_service import TemplatesService

AI_DRAFT_PREFIX = "[AI Draft] "


class AiTemplateService:
    def __init__(self, db: Session) -> None:
        self._users = UserRepository(db)
        self._repo = TemplatesRepository(db)
        self._templates = TemplatesService(db)

    def _require_active_ai_user(self) -> User:
        user = self._users.get_by_username(AI_ASSISTANT_USERNAME)
        if user is None:
            raise AccessDeniedError(f"'{AI_ASSISTANT_USERNAME}' user does not exist")
        if not user.is_active:
            raise AccessDeniedError(
                f"'{AI_ASSISTANT_USERNAME}' is disabled — an admin must activate it in "
                "Settings -> Users before this script can run."
            )
        return user

    @staticmethod
    def _require_prefix(name: str) -> None:
        if not name.startswith(AI_DRAFT_PREFIX):
            raise AccessDeniedError(f"AI template names must start with {AI_DRAFT_PREFIX!r}")

    def create(self, patch: dict[str, Any]) -> dict[str, Any]:
        user = self._require_active_ai_user()
        data = TemplateCreate(**patch)
        self._require_prefix(data.name)
        return self._templates.create_template(
            name=data.name,
            description=data.description,
            notes=data.notes,
            template_type=data.template_type,
            category=data.category,
            content=data.content,
            variables={k: v.model_dump() for k, v in data.variables.items()},
            pre_run_commands=data.pre_run_commands,
            pre_run_use_textfsm=data.pre_run_use_textfsm,
            nautobot_attributes=data.nautobot_attributes,
            credential_id=data.credential_id,
            batfish_config=data.batfish_config.model_dump() if data.batfish_config else None,
            created_by=AI_ASSISTANT_USERNAME,
            acting_user_id=user.id,
        )

    def update(self, template_id: int, patch: dict[str, Any]) -> dict[str, Any]:
        user = self._require_active_ai_user()
        existing = self._repo.get_by_id(template_id)
        if existing is None or not existing.is_active:
            raise TemplateNotFoundError(template_id)
        if existing.created_by != AI_ASSISTANT_USERNAME:
            raise AccessDeniedError(
                f"Template {template_id} was not created by the AI assistant; the AI may only "
                "edit its own drafts. Ask a human to rename or copy it."
            )
        data = TemplateUpdate(**patch)
        if data.name is not None:
            self._require_prefix(data.name)
        variables = (
            {k: v.model_dump() for k, v in data.variables.items()}
            if data.variables is not None
            else None
        )
        return self._templates.update_template(
            template_id,
            name=data.name,
            description=data.description,
            notes=data.notes,
            template_type=data.template_type,
            category=data.category,
            content=data.content,
            variables=variables,
            pre_run_commands=data.pre_run_commands,
            pre_run_use_textfsm=data.pre_run_use_textfsm,
            nautobot_attributes=data.nautobot_attributes,
            credential_id=data.credential_id,
            batfish_config=data.batfish_config.model_dump() if data.batfish_config else None,
            acting_user_id=user.id,
        )
