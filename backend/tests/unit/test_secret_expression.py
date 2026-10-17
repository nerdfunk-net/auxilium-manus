"""secret_expression: secret-valued step fields must be {path} references."""

from __future__ import annotations

import pytest

from services.workflow_context.secret_expression import (
    require_secret_expression,
    secret_expression_problem,
)


@pytest.mark.parametrize("value", ["{tacacs.new_key}", "{ nautobot.custom_fields.k }", "  {a.b}  "])
def test_accepts_whole_string_path_expression(value: str) -> None:
    assert secret_expression_problem(value) is None


@pytest.mark.parametrize(
    "value",
    ["", "   ", "s3cr3t", "{a} {b}", "{a|default('x')}", "{a} text", "prefix{a}", "{}", "{a}{b}"],
)
def test_rejects_everything_else(value: str) -> None:
    assert secret_expression_problem(value) is not None


def test_require_returns_stripped_expression() -> None:
    assert require_secret_expression(" {a.b} ", field="new_key", step_id="s") == "{a.b}"


def test_require_raises_with_step_id_and_field() -> None:
    with pytest.raises(ValueError) as excinfo:
        require_secret_expression("s3cr3t", field="new_key", step_id="add-to-ise")

    assert "add-to-ise" in str(excinfo.value)
    assert "new_key" in str(excinfo.value)
    assert "s3cr3t" not in str(excinfo.value)
