"""W5-06: the one place that binds a run and a source id to a Nautobot client."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from workflow_steps.common import nautobot_step
from workflow_steps.common.nautobot_step import bind_nautobot_client


def test_a_run_without_a_session_names_the_step() -> None:
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=None),
        pytest.raises(RuntimeError, match="update-nautobot-vlan: WorkflowRun has no active DB"),
    ):
        bind_nautobot_client(MagicMock(), "src-1", step_id="update-nautobot-vlan")


def test_credentials_are_resolved_for_the_source_and_step() -> None:
    db = MagicMock()
    credentials = MagicMock()
    service = MagicMock()
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=db),
        patch.object(
            nautobot_step, "resolve_nautobot_credentials", return_value=credentials
        ) as resolve,
        patch.object(
            nautobot_step.service_factory, "get_nautobot_app_service", return_value=service
        ),
    ):
        client = bind_nautobot_client(MagicMock(), "src-1", step_id="remove-from-nautobot")

    resolve.assert_called_once_with(db, "src-1", step_id="remove-from-nautobot")
    assert isinstance(client, CredentialsBoundNautobotClient)


def test_bind_nautobot_returns_credentials_service_and_a_client_built_from_both() -> None:
    db, credentials, service = MagicMock(), MagicMock(), MagicMock()
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=db),
        patch.object(
            nautobot_step, "resolve_nautobot_credentials", return_value=credentials
        ) as resolve,
        patch.object(
            nautobot_step.service_factory, "get_nautobot_app_service", return_value=service
        ) as get_service,
    ):
        bound = nautobot_step.bind_nautobot(MagicMock(), "src-1", step_id="exists-in-nautobot")

    resolve.assert_called_once_with(db, "src-1", step_id="exists-in-nautobot")
    get_service.assert_called_once_with()
    assert bound.credentials is credentials
    assert bound.service is service
    assert isinstance(bound.client, CredentialsBoundNautobotClient)
    assert bound.client._service is service
    assert bound.client._credentials is credentials


def test_bind_nautobot_names_the_step_when_the_run_has_no_session() -> None:
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=None),
        pytest.raises(RuntimeError, match="get-device-location: WorkflowRun has no active DB"),
    ):
        nautobot_step.bind_nautobot(MagicMock(), "src-1", step_id="get-device-location")
