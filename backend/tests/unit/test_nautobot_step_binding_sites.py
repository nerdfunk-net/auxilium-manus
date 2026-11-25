"""W5-06: the Nautobot steps bind through ``bind_nautobot`` with their own step id and use the
credentials and the service of that binding in the right places."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit._step_helpers import call_step, make_context, make_device
from workflow_steps.add_ip_to_nautobot import executor as add_ip
from workflow_steps.common import nautobot_step
from workflow_steps.exists_in_nautobot import executor as exists
from workflow_steps.get_device_location import executor as location


def test_add_ip_binds_with_its_step_id_and_keeps_service_and_credentials_apart() -> None:
    credentials, service = MagicMock(name="credentials"), MagicMock(name="service")
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=MagicMock()),
        patch.object(
            nautobot_step, "resolve_nautobot_credentials", return_value=credentials
        ) as resolve,
        patch.object(
            nautobot_step.service_factory, "get_nautobot_app_service", return_value=service
        ),
    ):
        bound = add_ip._bind_nautobot(MagicMock(), "src-1")

    assert resolve.call_args.args[1] == "src-1"
    assert resolve.call_args.kwargs == {"step_id": "add-ip-to-nautobot"}
    assert bound.service is service
    assert bound.credentials is credentials
    assert bound.client is not None
    assert bound.common is not None


def test_the_client_helper_returns_a_client_built_from_the_binding() -> None:
    credentials, service = MagicMock(), MagicMock()
    with (
        patch("workflow_steps.common.run_session.object_session", return_value=MagicMock()),
        patch.object(nautobot_step, "resolve_nautobot_credentials", return_value=credentials),
        patch.object(
            nautobot_step.service_factory, "get_nautobot_app_service", return_value=service
        ),
    ):
        client = nautobot_step.bind_nautobot_client(MagicMock(), "s", step_id="x")

    assert client._service is service
    assert client._credentials is credentials


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "step_id", "config"),
    [
        (exists, "exists-in-nautobot", {"nautobot_source_id": "src", "strategy": "name"}),
        (
            location,
            "get-device-location",
            {"nautobot_source_id": "src", "location_type": "City"},
        ),
    ],
)
async def test_the_steps_bind_with_their_own_step_id(module, step_id, config) -> None:
    bind = MagicMock(return_value=MagicMock(credentials=MagicMock(), service=MagicMock()))
    service_calls = AsyncMock(return_value={"data": {"devices": []}})
    bind.return_value.service.graphql_query = service_calls
    with patch.object(module, "bind_nautobot", bind):
        await call_step(
            module.execute,
            config=config,
            context=make_context([make_device("a")]),
            node_id="n1",
        )

    assert bind.call_args.kwargs == {"step_id": step_id}
    assert bind.call_args.args[1] == "src"
