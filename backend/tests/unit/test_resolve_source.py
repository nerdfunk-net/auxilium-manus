"""QW7 / W2-05: one `resolve_source` for the source-credential resolvers of the steps.

Seven private wrappers (ISE x4, ACI, Catalyst Center, Mattermost) wrote the same try/except; the
base ``SourceNotFoundError`` already formats ``"<display_name> source '<id>' not found"``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from services.aci.common.exceptions import AciValidationError
from services.aci.source_config_service import AciSourceNotFoundError
from services.catalyst_center.common.exceptions import CatalystCenterValidationError
from services.catalyst_center.source_config_service import CatalystCenterSourceNotFoundError
from services.ise.common.exceptions import ISEValidationError
from services.ise.source_config_service import ISESourceNotFoundError
from services.mattermost.common.exceptions import MattermostValidationError
from services.mattermost.source_config_service import MattermostSourceNotFoundError
from workflow_steps.common.source_credentials import resolve_source

_CASES = [
    (ISESourceNotFoundError, ISEValidationError, "ISE"),
    (AciSourceNotFoundError, AciValidationError, "Cisco ACI"),
    (CatalystCenterSourceNotFoundError, CatalystCenterValidationError, "Catalyst Center"),
    (MattermostSourceNotFoundError, MattermostValidationError, "Mattermost"),
]


def _service(**kwargs) -> MagicMock:
    service = MagicMock()
    service.resolve_credentials = MagicMock(**kwargs)
    return service


def test_returns_the_credentials() -> None:
    creds = object()
    service = _service(return_value=creds)
    assert resolve_source(service, "lab", step_id="s", invalid=ISEValidationError) is creds
    service.resolve_credentials.assert_called_once_with("lab")


@pytest.mark.parametrize(("not_found", "invalid", "label"), _CASES)
def test_an_unknown_source_is_a_config_error_naming_step_and_integration(
    not_found: type[Exception], invalid: type[Exception], label: str
) -> None:
    service = _service(side_effect=not_found("lab"))
    with pytest.raises(ValueError) as caught:
        resolve_source(service, "lab", step_id="some-step", invalid=invalid)
    assert str(caught.value) == f"some-step: {label} source 'lab' not found"
    assert isinstance(caught.value.__cause__, not_found)


@pytest.mark.parametrize(("not_found", "invalid", "label"), _CASES)
def test_an_invalid_source_config_keeps_its_sentence(
    not_found: type[Exception], invalid: type[Exception], label: str
) -> None:
    service = _service(side_effect=invalid("token is missing"))
    with pytest.raises(ValueError, match=r"^some-step: token is missing$"):
        resolve_source(service, "lab", step_id="some-step", invalid=invalid)


def test_any_other_error_is_not_swallowed() -> None:
    service = _service(side_effect=RuntimeError("db down"))
    with pytest.raises(RuntimeError, match="db down"):
        resolve_source(service, "lab", step_id="s", invalid=ISEValidationError)
