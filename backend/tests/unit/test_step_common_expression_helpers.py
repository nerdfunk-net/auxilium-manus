"""Safety net for ``template_content`` (42 %) and ``attribute_expression`` (43 %), W13-12.

``render-jinja-template`` reads its template through ``load_stored_template``; the Nautobot job
steps and others read parameters through ``resolve_attribute_expression``. Both are moved or
merged by P-K / P-N1.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.templates.exceptions import TemplateNotFoundError
from tests.unit._step_helpers import make_device
from workflow_steps.common import template_content
from workflow_steps.common.attribute_expression import resolve_attribute_expression

# ── load_stored_template ───────────────────────────────────────────────────────────────────────


def _load(record: object = None) -> tuple[str, MagicMock]:
    db = MagicMock()
    service = MagicMock()
    service.get_template.return_value = record
    with (
        patch.object(template_content, "get_db_session", return_value=db),
        patch.object(template_content, "TemplatesService", return_value=service),
    ):
        return template_content.load_stored_template(5, step_id="s"), db


def test_the_stored_template_content_is_returned_and_the_session_closed() -> None:
    text, db = _load({"content": "hostname {{ device.name }}"})

    assert text == "hostname {{ device.name }}"
    db.close.assert_called_once()


def test_a_template_without_content_is_empty_text() -> None:
    assert _load({"content": None})[0] == ""
    assert _load({})[0] == ""


def test_an_unknown_template_is_a_config_error_and_the_session_is_still_closed() -> None:
    db = MagicMock()
    service = MagicMock()
    service.get_template.side_effect = TemplateNotFoundError("5")
    with (
        patch.object(template_content, "get_db_session", return_value=db),
        patch.object(template_content, "TemplatesService", return_value=service),
        pytest.raises(ValueError, match="s: stored template 5 was not found"),
    ):
        template_content.load_stored_template(5, step_id="s")

    db.close.assert_called_once()


# ── resolve_attribute_expression ───────────────────────────────────────────────────────────────

_DEVICE = make_device(
    "d1", name="sw1", attribute_bags={"custom": {"vid": "100", "empty": "", "nested": {"a": 1}}}
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("literal text", "literal text"),
        ("  padded  ", "padded"),
        ("", None),
        ("   ", None),
        ("{custom.vid}", "100"),
        ("{ custom.vid }", "100"),
        ("{custom.missing}", None),
        ("{custom.missing | default('fallback')}", "fallback"),
        ('{custom.missing | default("dq")}', "dq"),
        ("{custom.vid | default('fallback')}", "100"),
        ("{custom.nested}", None),
        ("{device.name}", "sw1"),
    ],
)
def test_expressions_resolve_against_the_device(raw: str, expected: str | None) -> None:
    assert resolve_attribute_expression(_DEVICE, raw) == expected


def test_a_sealed_secret_is_revealed_only_when_asked() -> None:
    from core.crypto import EncryptionService
    from services.workflow_context.secret_fields import seal_secret

    sealed = seal_secret("pa55word-value", encryption=EncryptionService("k" * 32))
    device = make_device("d1", attribute_bags={"tacacs": {"shared_secret": sealed}})

    hidden = resolve_attribute_expression(device, "{tacacs.shared_secret}", reveal_secrets=False)

    assert hidden != "pa55word-value"
