"""AiTemplateService: the AI may create "[AI Draft] " templates and edit only its own."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.domain_exceptions import AccessDeniedError
from services.templates.ai_template_service import AI_DRAFT_PREFIX, AiTemplateService
from services.templates.exceptions import TemplateNotFoundError


def _service(*, active: bool = True, existing: object | None = None) -> AiTemplateService:
    service = AiTemplateService(MagicMock())
    service._users = MagicMock()
    user = MagicMock(is_active=active)
    user.id = 42
    service._users.get_by_username.return_value = user
    service._repo = MagicMock()
    service._repo.get_by_id.return_value = existing
    service._templates = MagicMock()
    return service


def _template(*, created_by: str | None, is_active: bool = True) -> MagicMock:
    return MagicMock(created_by=created_by, is_active=is_active)


_CREATE = {"name": f"{AI_DRAFT_PREFIX}Backup", "content": "hostname {{ name }}"}


def test_create_without_prefix_is_denied() -> None:
    service = _service()

    with pytest.raises(AccessDeniedError, match="AI Draft"):
        service.create({**_CREATE, "name": "Backup"})

    service._templates.create_template.assert_not_called()


def test_create_with_prefix_records_ai_as_creator() -> None:
    service = _service()

    service.create(_CREATE)

    kwargs = service._templates.create_template.call_args.kwargs
    assert kwargs["created_by"] == "ai-assistant"
    assert kwargs["name"] == f"{AI_DRAFT_PREFIX}Backup"
    assert kwargs["acting_user_id"] == 42


def test_update_of_a_human_template_is_denied() -> None:
    service = _service(existing=_template(created_by="alice"))

    with pytest.raises(AccessDeniedError, match="not created by the AI"):
        service.update(7, {"content": "x"})

    service._templates.update_template.assert_not_called()


def test_update_of_a_template_with_no_creator_is_denied() -> None:
    service = _service(existing=_template(created_by=None))

    with pytest.raises(AccessDeniedError):
        service.update(7, {"content": "x"})


def test_update_of_its_own_draft_is_applied() -> None:
    service = _service(existing=_template(created_by="ai-assistant"))

    service.update(7, {"content": "new"})

    service._templates.update_template.assert_called_once()
    assert service._templates.update_template.call_args.args[0] == 7
    assert service._templates.update_template.call_args.kwargs["content"] == "new"


def test_update_renaming_away_from_the_prefix_is_denied() -> None:
    service = _service(existing=_template(created_by="ai-assistant"))

    with pytest.raises(AccessDeniedError, match="AI Draft"):
        service.update(7, {"name": "Backup"})

    service._templates.update_template.assert_not_called()


@pytest.mark.parametrize("existing", [None, _template(created_by="ai-assistant", is_active=False)])
def test_update_of_a_missing_or_inactive_template_is_not_found(existing) -> None:
    service = _service(existing=existing)

    with pytest.raises(TemplateNotFoundError):
        service.update(7, {"content": "x"})


def test_inactive_ai_user_is_denied_for_create_and_update() -> None:
    service = _service(active=False, existing=_template(created_by="ai-assistant"))

    with pytest.raises(AccessDeniedError, match="disabled"):
        service.create(_CREATE)
    with pytest.raises(AccessDeniedError, match="disabled"):
        service.update(7, {"content": "x"})


def test_missing_ai_user_is_denied() -> None:
    service = _service()
    service._users.get_by_username.return_value = None

    with pytest.raises(AccessDeniedError, match="does not exist"):
        service.create(_CREATE)
