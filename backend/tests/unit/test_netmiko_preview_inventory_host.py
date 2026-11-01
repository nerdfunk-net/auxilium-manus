"""``NetmikoPreviewService.run_commands`` for a host that came from the inventory."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from core.config import settings
from core.domain_exceptions import ValidationFailedError
from models.netmiko import NetmikoRunCommandsRequest
from services.network.netmiko.connection import CommandResult
from services.network.netmiko.preview_service import NetmikoPreviewService


def _service() -> NetmikoPreviewService:
    credentials = MagicMock()
    credentials.get_credential_by_id.return_value = {"type": "ssh", "username": "admin"}
    credentials.get_decrypted_password.return_value = "pw"
    return NetmikoPreviewService(credentials)


def _request(host: str = "10.1.2.3") -> NetmikoRunCommandsRequest:
    return NetmikoRunCommandsRequest(
        host=host,
        platform="cisco_ios",
        network_driver="cisco_ios",
        credential_id=5,
        commands=["show version"],
    )


def _run(service: NetmikoPreviewService, request, **kwargs):
    with patch("services.network.netmiko.preview_service.NetmikoService") as cls:

        async def send(**_k):
            return CommandResult(success=True, command_outputs={"show version": "ok"})

        cls.return_value.send_commands.side_effect = send
        return asyncio.run(service.run_commands(request, acting_user_id=3, **kwargs))


def test_a_typed_host_is_refused_in_production_without_the_arbitrary_host_flag(monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "allow_netmiko_arbitrary_hosts", False)

    with pytest.raises(ValidationFailedError):
        _run(_service(), _request())


def test_an_inventory_host_does_not_need_the_arbitrary_host_flag(monkeypatch) -> None:
    monkeypatch.setattr(settings, "environment", "production")
    monkeypatch.setattr(settings, "allow_netmiko_arbitrary_hosts", False)

    response = _run(_service(), _request(), host_from_inventory=True)

    assert response.success
    assert response.commands[0].raw == "ok"


@pytest.mark.parametrize("host", ["127.0.0.1", "169.254.169.254", "metadata.google.internal"])
def test_an_inventory_host_still_gets_the_sanity_rules(monkeypatch, host: str) -> None:
    monkeypatch.setattr(settings, "environment", "production")

    with pytest.raises(ValidationFailedError):
        _run(_service(), _request(host), host_from_inventory=True)


def test_a_read_timeout_is_passed_on_to_netmiko_and_defaults_to_none() -> None:
    service = _service()
    with patch("services.network.netmiko.preview_service.NetmikoService") as cls:
        seen: list[dict] = []

        async def send(**kwargs):
            seen.append(kwargs)
            return CommandResult(success=True, command_outputs={"show version": "ok"})

        cls.return_value.send_commands.side_effect = send
        asyncio.run(service.run_commands(_request(), acting_user_id=3, host_from_inventory=True))
        asyncio.run(
            service.run_commands(
                _request(), acting_user_id=3, host_from_inventory=True, read_timeout=120
            )
        )

    assert [k["read_timeout"] for k in seen] == [None, 120]
