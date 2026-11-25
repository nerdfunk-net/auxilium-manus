"""``controller_failure_outcomes``: one failure outcome, a cause record, no controller text."""

from __future__ import annotations

import logging

from models.failure import FailureInfo
from models.workflow_context import DeviceContext, WorkflowContext
from services.aci.common.exceptions import AciAPIError
from workflow_steps.common.controller_failure import controller_failure_outcomes

_LOGGER = logging.getLogger("test.controller_failure")


def _context() -> WorkflowContext:
    device = DeviceContext(id="d1", name="d1", hostname="d1")
    return WorkflowContext(run_id="r", workflow_id="w", devices={"d1": device})


def test_a_classified_error_keeps_its_record() -> None:
    error = AciAPIError("down", http_status=503)
    context = _context()
    outcomes = controller_failure_outcomes(
        context, error, label="APIC", step_id="s", logger=_LOGGER
    )
    assert [o.name for o in outcomes] == ["failure"]
    assert outcomes[0].summary == "APIC request failed"
    assert outcomes[0].failure is not None and outcomes[0].failure.kind == "server_error"
    assert outcomes[0].context is context


def test_an_unclassified_error_gets_the_controller_record() -> None:
    outcomes = controller_failure_outcomes(
        _context(), RuntimeError("x"), label="Nautobot", step_id="s", logger=_LOGGER
    )
    assert outcomes[0].failure == FailureInfo(phase="api", kind="unknown", hint="check_controller")
    assert outcomes[0].summary == "Nautobot request failed"


def test_the_log_names_the_class_not_the_controller_text(caplog) -> None:
    with caplog.at_level(logging.WARNING, logger=_LOGGER.name):
        controller_failure_outcomes(
            _context(),
            RuntimeError("token=SECRET-VALUE"),
            label="APIC",
            step_id="s",
            logger=_LOGGER,
        )
    assert "RuntimeError" in caplog.text
    assert "SECRET-VALUE" not in caplog.text
