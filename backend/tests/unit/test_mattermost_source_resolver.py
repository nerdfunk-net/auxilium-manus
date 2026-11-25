"""resolve_mattermost_credentials: the one resolver of notify-mattermost and notify-on-error."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.mattermost.common.exceptions import MattermostValidationError
from services.mattermost.source_config_service import MattermostSourceNotFoundError
from workflow_steps.common.mattermost_source import resolve_mattermost_credentials

_FACTORY = "workflow_steps.common.mattermost_source.service_factory"


def _resolve(**kwargs: object) -> object:
    with patch(_FACTORY) as factory:
        service = factory.build_mattermost_source_config_service.return_value
        service.resolve_credentials.configure_mock(**kwargs)
        credentials = resolve_mattermost_credentials(MagicMock(), "chat", step_id="notify")
        service.resolve_credentials.assert_called_once_with("chat")
        return credentials


def test_returns_the_resolved_credentials() -> None:
    sentinel = object()

    assert _resolve(return_value=sentinel) is sentinel


def test_an_unknown_source_is_a_value_error_naming_step_and_source() -> None:
    with pytest.raises(ValueError, match=r"notify: Mattermost source 'chat' not found") as info:
        _resolve(side_effect=MattermostSourceNotFoundError("chat"))

    assert isinstance(info.value.__cause__, MattermostSourceNotFoundError)


def test_an_invalid_source_config_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="notify: bad token") as info:
        _resolve(side_effect=MattermostValidationError("bad token"))

    assert isinstance(info.value.__cause__, MattermostValidationError)
