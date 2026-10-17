"""S3-03: a ``secret`` run input is sealed on receipt and never returned in plaintext."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from models.workflows import StaticAttributeDef
from services.execution.run_input_validation import RunInputValidationError, resolve_run_inputs
from services.execution.run_service import _run_to_response, _run_to_summary
from services.execution.schedule_service import ScheduleService
from services.workflow_context.secret_fields import (
    REDACTED_PLACEHOLDER,
    is_sealed_secret,
    redact_secrets_in_data,
    unwrap_secret,
)
from workflow_steps.common.run_param_reference import resolve_config_reference

SECRET = "N3w-TACACS-Key-2026"
ATTRS = [{"name": "new_tacacs_key", "type": "secret", "required": True}]


def _fake_sealer(value: str) -> dict:
    return {"__sealed__": True, "v": 1, "ct": f"ct-of-{len(value)}"}


def test_secret_attribute_rejects_default() -> None:
    with pytest.raises(ValidationError):
        StaticAttributeDef(name="k", type="secret", default="x")


def test_secret_input_is_persisted_sealed() -> None:
    result = resolve_run_inputs(ATTRS, {"new_tacacs_key": SECRET})
    assert is_sealed_secret(result["new_tacacs_key"])
    assert SECRET not in json.dumps(result)
    assert unwrap_secret(result["new_tacacs_key"]) == SECRET
    # idempotent: a schedule / change request replays the stored envelope
    again = resolve_run_inputs(ATTRS, result)
    assert again == result


@pytest.mark.parametrize("bad", ["", None, 5, ["x"]])
def test_secret_input_must_be_non_empty_string(bad) -> None:
    with pytest.raises(RunInputValidationError):
        resolve_run_inputs(ATTRS, {"new_tacacs_key": bad})


def _run(run_inputs: dict) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=1,
        uuid="u",
        workflow_id=1,
        triggered_by_id=1,
        status="completed",
        trigger_type="manual",
        current_node_id=None,
        debug_message=None,
        approval_state=None,
        device_ids=[],
        run_inputs=run_inputs,
        hatchet_run_id=None,
        error_message=None,
        error_category=None,
        error_id=None,
        started_at=now,
        finished_at=now,
        created_at=now,
        updated_at=now,
    )


def test_run_response_redacts_secret_input() -> None:
    sealed = resolve_run_inputs(ATTRS, {"new_tacacs_key": SECRET})
    expected = {"new_tacacs_key": REDACTED_PLACEHOLDER}
    assert _run_to_summary(_run(sealed), "u").run_inputs == expected
    assert _run_to_response(_run(sealed), "u", []).run_inputs == expected


def test_redact_secrets_in_data_hides_envelope() -> None:
    sealed = resolve_run_inputs(ATTRS, {"new_tacacs_key": SECRET})
    assert redact_secrets_in_data({"run_inputs": sealed}) == {
        "run_inputs": {"new_tacacs_key": REDACTED_PLACEHOLDER}
    }


def test_schedule_edit_keeps_stored_secret() -> None:
    workflow = SimpleNamespace(static_attributes=ATTRS)
    stored = resolve_run_inputs(ATTRS, {"new_tacacs_key": SECRET})
    keep = ScheduleService._keep_stored_secrets
    assert keep(workflow, {}, stored) == stored
    assert keep(workflow, {"new_tacacs_key": REDACTED_PLACEHOLDER}, stored) == stored
    assert keep(workflow, {"new_tacacs_key": "fresh"}, stored)["new_tacacs_key"] == "fresh"


def test_run_param_reference_refuses_secret() -> None:
    sealed = resolve_run_inputs(ATTRS, {"new_tacacs_key": SECRET})
    with pytest.raises(ValueError, match="secret run parameter"):
        resolve_config_reference(
            {"src": "run_param", "param": "new_tacacs_key"},
            source_key="src",
            param_key="param",
            literal_key="lit",
            run_inputs=sealed,
        )
