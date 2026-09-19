"""Load a stored Template row's content for a step's Jinja rendering.

Shared by ``render-jinja-template`` and ``update-config-context`` — both
resolve a ``template_id`` from the Templates library to raw template text
before handing it to ``jinja_render.render_jinja_template``.
"""

from __future__ import annotations

from core.database import get_db_session
from services.templates.exceptions import TemplateNotFoundError
from services.templates.templates_service import TemplatesService


def load_stored_template(template_id: int, *, step_id: str) -> str:
    """Return the raw content of stored ``Template`` *template_id*.

    Raises ``ValueError`` (a configuration error, per the step contract) when
    the template does not exist.
    """
    db = get_db_session()
    try:
        record = TemplatesService(db).get_template(template_id)
    except TemplateNotFoundError as exc:
        raise ValueError(f"{step_id}: stored template {template_id} was not found") from exc
    finally:
        db.close()
    return str(record.get("content") or "")
