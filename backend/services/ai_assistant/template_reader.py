"""DB-backed ``TemplateReader`` for the assistant's template tools.

Tools run inside an async generator after the request's session has been released, so each call
opens its own short-lived session (in a worker thread) and checks the calling user's RBAC itself.
"""

from __future__ import annotations

import asyncio
from typing import Any

from core.database import SessionLocal
from services.ai_assistant.tools.template_tools import TemplatePermissionError
from services.auth.rbac_service import RBACService
from services.templates.exceptions import TemplateNotFoundError
from services.templates.templates_service import TemplatesService


class DbTemplateReader:
    def __init__(self, user_id: int) -> None:
        self._user_id = user_id

    async def list_templates(self, search: str | None, limit: int) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self._list, search, limit)

    async def get_template(self, template_id: int) -> dict[str, Any] | None:
        return await asyncio.to_thread(self._get, template_id)

    def _list(self, search: str | None, limit: int) -> list[dict[str, Any]]:
        with SessionLocal() as db:
            self._require_read(db)
            return TemplatesService(db).list_templates(search=search)[:limit]

    def _get(self, template_id: int) -> dict[str, Any] | None:
        with SessionLocal() as db:
            self._require_read(db)
            try:
                return TemplatesService(db).get_template(template_id)
            except TemplateNotFoundError:
                return None

    def _require_read(self, db: Any) -> None:
        if not RBACService(db).has_permission(self._user_id, "templates", "read"):
            raise TemplatePermissionError
