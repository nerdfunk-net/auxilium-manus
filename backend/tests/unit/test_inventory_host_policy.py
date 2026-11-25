"""W3b-14: SSH and ICMP steps do not dial a host the host policy refuses (outside development)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from services.network.netmiko.session_pool import DeviceSessionPool
from tests.unit._step_helpers import make_device
from workflow_steps.common.device_runner import Fail
from workflow_steps.reachable import executor as reachable

_POOL_SETTINGS = "services.network.netmiko.session_pool.settings"
_SESSION = "services.network.netmiko.session_pool.NetmikoDeviceSession"


def _settings(environment: str, allow: bool = False) -> MagicMock:
    return MagicMock(
        environment=environment, allow_netmiko_arbitrary_hosts=allow, netmiko_keepalive_seconds=0
    )


async def _run(pool: DeviceSessionPool, host: str):
    return await pool.run_on_device(
        host=host,
        device_type="cisco_ios",
        credential_reference="c",
        username="u",
        password="p",
        op=lambda session: "ran",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_pool_refuses_a_blocked_host_before_any_session_exists(enabled: bool) -> None:
    pool = DeviceSessionPool(enabled=enabled)
    with patch(_POOL_SETTINGS, _settings("production")), patch(_SESSION) as session_cls:
        with pytest.raises(ValueError, match="not allowed"):
            await _run(pool, "169.254.169.254")
    session_cls.assert_not_called()


@pytest.mark.asyncio
async def test_pool_probe_login_refuses_a_blocked_host() -> None:
    pool = DeviceSessionPool()
    with patch(_POOL_SETTINGS, _settings("production")), patch(_SESSION) as session_cls:
        with pytest.raises(ValueError, match="not allowed"):
            await pool.probe_login(host="127.0.0.1", device_type="x", username="u", password="p")
    session_cls.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("env", [("development", False), ("production", True)])
async def test_pool_lets_a_blocked_host_through_in_development_or_with_the_switch(env) -> None:
    pool = DeviceSessionPool(enabled=False)
    with patch(_POOL_SETTINGS, _settings(*env)), patch(_SESSION):
        assert await _run(pool, "127.0.0.1") == "ran"


@pytest.mark.asyncio
async def test_pool_lets_a_normal_host_through_in_production() -> None:
    pool = DeviceSessionPool(enabled=False)
    with patch(_POOL_SETTINGS, _settings("production")), patch(_SESSION):
        assert await _run(pool, "10.0.0.1") == "ran"


@pytest.mark.asyncio
async def test_reachable_refuses_a_blocked_host_without_pinging() -> None:
    device = make_device("d1", name="r1", primary_ip4="169.254.169.254")
    with (
        patch("workflow_steps.reachable.executor.settings", _settings("production")),
        patch("workflow_steps.reachable.executor.async_ping") as ping,
    ):
        result = await reachable._ping_device(
            device, node_id="n", ping_count=1, required_replies=1, timeout_seconds=1.0
        )
    ping.assert_not_called()
    assert isinstance(result, Fail)
    assert result.code == "host_not_allowed"
    assert result.failure is not None and result.failure.kind == "bad_request"
