"""W6-03 / W5-06: the ISE and Nautobot source preambles live in ``workflow_steps/common`` only.

A step asks ``common/ise_step.py`` for its ISE device service and pre-flight, and
``common/nautobot_step.py::bind_nautobot`` for its Nautobot client; it never builds the source
config service, the bound client or the connection check itself.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from models.workflow_context import WorkflowContext
from services.ise.common.exceptions import ISEAPIError, ISEValidationError
from services.ise.source_config_service import ISESourceNotFoundError
from workflow_steps.common import ise_step

STEPS = Path(__file__).resolve().parents[2] / "workflow_steps"
FORBIDDEN = (
    "CredentialsBoundNautobotClient(",
    "build_ise_source_config_service",
    ".test_connection()",
)


def _offenders() -> list[str]:
    found = []
    for path in sorted(STEPS.rglob("*.py")):
        if "common" in path.relative_to(STEPS).parts:
            continue
        text = path.read_text()
        found += [f"{path.relative_to(STEPS)}: {needle}" for needle in FORBIDDEN if needle in text]
    return found


def test_no_step_builds_its_own_source_preamble() -> None:
    assert _offenders() == []


# --- common/ise_step.py ------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_reachable_ise_passes_the_preflight() -> None:
    service = MagicMock(test_connection=AsyncMock(return_value=None))

    context = WorkflowContext(run_id="r", workflow_id="w")

    assert await ise_step.preflight_ise(service, context, "lab", step_id="s") is None


@pytest.mark.asyncio
async def test_an_unreachable_ise_fails_the_whole_context_with_its_cause() -> None:
    error = ISEAPIError("connection refused", code="transport")
    service = MagicMock(test_connection=AsyncMock(side_effect=error))
    context = WorkflowContext(run_id="r", workflow_id="w")

    outcomes = await ise_step.preflight_ise(service, context, "lab", step_id="s")

    assert outcomes is not None and len(outcomes) == 1
    (outcome,) = outcomes
    assert outcome.name == "failure"
    assert outcome.context is context
    assert outcome.summary == "could not reach ISE source 'lab': connection refused"
    assert outcome.failure == error.failure


def test_the_device_service_is_built_from_the_run_session_and_source() -> None:
    run = MagicMock()
    db = MagicMock()
    credentials = MagicMock()
    config = MagicMock()
    config.resolve_credentials.return_value = credentials
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=db),
        patch.object(ise_step.service_factory, "build_ise_source_config_service") as build_cfg,
        patch.object(ise_step.service_factory, "build_ise_network_device_service") as build_svc,
    ):
        build_cfg.return_value = config
        service = ise_step.build_ise_device_service(run, "lab", step_id="s")

    build_cfg.assert_called_once_with(db)
    config.resolve_credentials.assert_called_once_with("lab")
    build_svc.assert_called_once_with(credentials)
    assert service is build_svc.return_value


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (ISESourceNotFoundError("lab"), "s: ISE source 'lab' not found"),
        (ISEValidationError("no password"), "s: no password"),
    ],
)
def test_a_bad_source_is_a_config_error(error: Exception, message: str) -> None:
    config = MagicMock()
    config.resolve_credentials.side_effect = error
    with (
        patch.object(
            ise_step.service_factory, "build_ise_source_config_service", return_value=config
        ),
        pytest.raises(ValueError, match=message),
    ):
        ise_step.resolve_ise_credentials(MagicMock(), "lab", step_id="s")


def test_a_run_without_a_session_is_a_bug() -> None:
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=None),
        pytest.raises(RuntimeError, match="no active DB session"),
    ):
        ise_step.ise_credentials(MagicMock(), "lab", step_id="s")


def test_add_to_ise_builds_its_group_service_with_the_source_credentials() -> None:
    from workflow_steps.add_to_ise import executor as add_mod

    credentials = MagicMock()
    with (
        patch.object(add_mod, "ise_credentials", return_value=credentials) as resolve,
        patch.object(add_mod.service_factory, "build_ise_network_device_group_service") as build,
    ):
        add_mod._build_group_ensurer(MagicMock(), "lab")

    resolve.assert_called_once()
    assert resolve.call_args.args[1] == "lab"
    build.assert_called_once_with(credentials)


@pytest.mark.parametrize("module", ["update_config_context", "update_nautobot_device"])
def test_the_update_steps_hand_out_the_source_binding(module: str) -> None:
    import importlib

    from workflow_steps.common import nautobot_step

    mod = importlib.import_module(f"workflow_steps.{module}.executor")
    credentials = MagicMock()
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=MagicMock()),
        patch.object(nautobot_step, "resolve_nautobot_credentials", return_value=credentials),
        patch.object(nautobot_step.service_factory, "get_nautobot_app_service", return_value="svc"),
    ):
        service, resolved, update_service = mod._build_update_service(MagicMock(), "src")

    assert (service, resolved) == ("svc", credentials)
    assert update_service is not None
