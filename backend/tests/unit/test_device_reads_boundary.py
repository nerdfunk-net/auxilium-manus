"""W3b (P-C step 3): the per-device boundary of the device-read steps.

``get-device-configs``, ``read-config``, ``login-successful`` and ``reachable`` run on
``run_per_device``: an unexpected exception fails **that device only**, its text never reaches the
stored run (class name + ``FailureInfo``), and every failure carries a ``FailureInfo``.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from icmplib import ICMPLibError, NameLookupError

from models.failure import FailureInfo
from models.workflow_context import DeviceStatus
from services.artifacts import InMemoryArtifactService
from services.network.netmiko.connection import ConfigResult, NetmikoConnectionError
from tests.unit._step_helpers import (
    call_step,
    make_context,
    make_device,
    patch_object_session,
    patch_ssh_credential,
)
from workflow_steps.get_device_configs.executor import execute as get_configs_execute
from workflow_steps.login_successful.executor import execute as login_execute
from workflow_steps.reachable.executor import MAX_CONCURRENT_PINGS
from workflow_steps.reachable.executor import execute as reachable_execute
from workflow_steps.read_config.executor import execute as read_config_execute

_GDC = "workflow_steps.get_device_configs.executor"
_LOGIN = "workflow_steps.login_successful.executor"
_REACH = "workflow_steps.reachable.executor"
_READ = "workflow_steps.read_config.executor"
_SECRET = "s3cr3t-driver-text 10.9.9.9"


def _failed(outcomes, device_id: str):
    failure = next(o for o in outcomes if o.name == "failure")
    return failure.context.devices[device_id]


# --- get-device-configs --------------------------------------------------------------------


@contextmanager
def _gdc_netmiko(get_configs: AsyncMock) -> Generator[None]:
    with (
        patch_ssh_credential(_GDC),
        patch_object_session(),
        patch(f"{_GDC}.NetmikoService") as netmiko_cls,
    ):
        netmiko_cls.return_value.get_configs = get_configs
        yield


class _ExplodingArtifacts(InMemoryArtifactService):
    async def store(self, **kwargs):  # type: ignore[override]
        raise OSError(_SECRET)


@pytest.mark.asyncio
async def test_get_device_configs_hides_the_text_of_an_unexpected_error() -> None:
    devices = [
        make_device("a", primary_ip4="10.0.0.1/24"),
        make_device("b", primary_ip4="10.0.0.2"),
    ]
    ok = ConfigResult(success=True, running_config="hostname x\n")
    with _gdc_netmiko(AsyncMock(return_value=ok)):
        outcomes = await call_step(
            get_configs_execute,
            {"config_format": "running", "credential_reference": "lab"},
            make_context(devices),
            artifact_service=_ExplodingArtifacts(),
        )

    assert {o.name for o in outcomes} == {"success", "failure"}
    for device_id in ("a", "b"):
        error = _failed(outcomes, device_id).errors[-1]
        assert error.message == "OSError"
        assert _SECRET not in error.message
        assert error.failure is not None


@pytest.mark.asyncio
async def test_get_device_configs_driver_exception_text_is_not_stored() -> None:
    raising = AsyncMock(side_effect=NetmikoConnectionError(_SECRET))
    with _gdc_netmiko(raising):
        outcomes = await call_step(
            get_configs_execute,
            {"config_format": "running", "credential_reference": "lab"},
            make_context([make_device("a", primary_ip4="10.0.0.1")]),
        )

    error = _failed(outcomes, "a").errors[-1]
    assert error.message == "NetmikoConnectionError"
    assert error.code == "netmikoconnectionerror"


@pytest.mark.asyncio
async def test_get_device_configs_one_failing_device_keeps_the_others() -> None:
    async def fetch(**kwargs):
        if kwargs["host"] == "10.0.0.2":
            raise KeyError(_SECRET)
        return ConfigResult(success=True, running_config="hostname x\n")

    devices = [make_device("a", primary_ip4="10.0.0.1"), make_device("b", primary_ip4="10.0.0.2")]
    with _gdc_netmiko(AsyncMock(side_effect=fetch)):
        outcomes = await call_step(
            get_configs_execute,
            {"config_format": "running", "credential_reference": "lab"},
            make_context(devices),
        )

    by_name = {o.name: o for o in outcomes}
    assert set(by_name["success"].context.devices) == {"a"}
    assert set(by_name["failure"].context.devices) == {"b"}


@pytest.mark.asyncio
async def test_get_device_configs_keeps_the_error_text_of_a_failed_result() -> None:
    result = ConfigResult(success=False, error="Config retrieval failed: no prompt")
    with _gdc_netmiko(AsyncMock(return_value=result)):
        outcomes = await call_step(
            get_configs_execute,
            {"config_format": "running", "credential_reference": "lab"},
            make_context([make_device("a", primary_ip4="10.0.0.1")]),
        )

    error = _failed(outcomes, "a").errors[-1]
    assert error.message == "Config retrieval failed: no prompt"
    assert error.code == "config_retrieval_failed"


@pytest.mark.asyncio
async def test_get_device_configs_device_without_host_fails_with_missing_host() -> None:
    nameless = make_device("a").model_copy(update={"hostname": None, "primary_ip4": None})
    with _gdc_netmiko(AsyncMock()):
        outcomes = await call_step(
            get_configs_execute,
            {"config_format": "running", "credential_reference": "lab"},
            make_context([nameless]),
        )

    error = _failed(outcomes, "a").errors[-1]
    assert error.code == "missing_host"
    assert error.message == "Device a has no hostname or primary IP"


@pytest.mark.asyncio
async def test_get_device_configs_logs_one_line_per_device(
    caplog: pytest.LogCaptureFixture,
) -> None:
    ok = ConfigResult(success=True, running_config="hostname x\n")
    with caplog.at_level(logging.INFO), _gdc_netmiko(AsyncMock(return_value=ok)):
        await call_step(
            get_configs_execute,
            {"config_format": "running", "credential_reference": "lab"},
            make_context([make_device("a", primary_ip4="10.0.0.1")]),
        )

    text = caplog.text
    assert "get-device-configs device 1/1 id=a host=10.0.0.1: connecting" in text
    assert "get-device-configs device 1/1 id=a host=10.0.0.1: ok" in text


# --- read-config ---------------------------------------------------------------------------


@contextmanager
def _export_dir() -> Generator[Path]:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        service = MagicMock()
        service.resolved_export_directory.return_value = root
        with (
            patch(
                "workflow_steps.common.file_source_root.get_db_session", return_value=MagicMock()
            ),
            patch(
                "workflow_steps.common.file_source_root.GeneralSettingsService",
                return_value=service,
            ),
        ):
            yield root


def _read_config(path_template: str = "{device.name}.cfg", **extra):
    return {"source": "filesystem", "path_template": path_template, **extra}


@pytest.mark.asyncio
async def test_read_config_missing_file_carries_a_failure_record() -> None:
    with _export_dir():
        outcomes = await call_step(
            read_config_execute, _read_config(), make_context([make_device("a")])
        )

    error = _failed(outcomes, "a").errors[-1]
    assert error.code == "filenotfounderror"
    assert error.failure is not None


@pytest.mark.asyncio
async def test_read_config_refuses_an_empty_file() -> None:
    with _export_dir() as root:
        (root / "a.cfg").write_text("  \n")
        artifacts = InMemoryArtifactService()
        outcomes = await call_step(
            read_config_execute,
            _read_config(),
            make_context([make_device("a")]),
            artifact_service=artifacts,
        )

    device = _failed(outcomes, "a")
    assert device.status == DeviceStatus.FAILED
    assert device.errors[-1].code == "empty_config"
    assert device.errors[-1].failure is not None
    assert device.running_config_ref is None


@pytest.mark.asyncio
async def test_read_config_refuses_a_file_above_the_size_cap_without_reading_it() -> None:
    with _export_dir() as root:
        (root / "a.cfg").write_text("hostname a\n" + "! pad\n" * 10)
        (root / "b.cfg").write_text("hostname b\n")
        artifacts = InMemoryArtifactService()
        with patch("workflow_steps.read_config.executor.MAX_CONFIG_BYTES", 40):
            outcomes = await call_step(
                read_config_execute,
                _read_config(),
                make_context([make_device("a"), make_device("b")]),
                artifact_service=artifacts,
            )

    by_name = {o.name: o for o in outcomes}
    assert set(by_name["success"].context.devices) == {"b"}
    device = by_name["failure"].context.devices["a"]
    error = device.errors[-1]
    assert error.code == "file_too_large"
    assert error.message == "config file is larger than 40 bytes: a.cfg"
    assert error.failure == FailureInfo(phase="config", kind="payload_too_large")
    assert device.running_config_ref is None


@pytest.mark.asyncio
async def test_read_config_accepts_a_file_exactly_at_the_cap() -> None:
    with _export_dir() as root:
        (root / "a.cfg").write_text("x" * 40)
        with patch("workflow_steps.read_config.executor.MAX_CONFIG_BYTES", 40):
            outcomes = await call_step(
                read_config_execute, _read_config(), make_context([make_device("a")])
            )

    assert [o.name for o in outcomes] == ["success"]


@pytest.mark.asyncio
async def test_read_config_one_bad_device_keeps_the_others() -> None:
    with _export_dir() as root:
        (root / "a.cfg").write_text("hostname a\n")
        outcomes = await call_step(
            read_config_execute,
            _read_config(),
            make_context([make_device("a"), make_device("b")]),
        )

    by_name = {o.name: o for o in outcomes}
    assert set(by_name["success"].context.devices) == {"a"}
    assert set(by_name["failure"].context.devices) == {"b"}


@pytest.mark.asyncio
async def test_read_config_artifact_store_error_fails_only_that_device() -> None:
    with _export_dir() as root:
        (root / "a.cfg").write_text("hostname a\n")
        outcomes = await call_step(
            read_config_execute,
            _read_config(),
            make_context([make_device("a")]),
            artifact_service=_ExplodingArtifacts(),
        )

    error = _failed(outcomes, "a").errors[-1]
    assert error.message == "OSError"
    assert _SECRET not in error.message


# --- login-successful ----------------------------------------------------------------------


@contextmanager
def _login_netmiko(test_login: AsyncMock) -> Generator[None]:
    with (
        patch_ssh_credential(_LOGIN),
        patch_object_session(),
        patch(f"{_LOGIN}.NetmikoService") as netmiko_cls,
    ):
        netmiko_cls.return_value.test_login = test_login
        yield


_LOGIN_CONFIG = {"credential_reference": "lab"}


@pytest.mark.asyncio
async def test_login_failure_text_is_not_stored_in_the_bag_or_the_message() -> None:
    info_error = NetmikoConnectionError(_SECRET)
    with _login_netmiko(AsyncMock(side_effect=info_error)):
        outcomes = await call_step(
            login_execute,
            _LOGIN_CONFIG,
            make_context([make_device("a", primary_ip4="10.0.0.1", network_driver="cisco_ios")]),
        )

    device = _failed(outcomes, "a")
    assert device.errors[-1].message == "NetmikoConnectionError"
    login = device.parsed["node-1"]["login"]
    assert login["login_ok"] is False
    assert _SECRET not in str(login)
    assert login["error"] == device.errors[-1].failure.kind  # a closed code, not the text


@pytest.mark.asyncio
async def test_login_not_alive_carries_a_failure_record() -> None:
    with _login_netmiko(AsyncMock(return_value=False)):
        outcomes = await call_step(
            login_execute,
            _LOGIN_CONFIG,
            make_context([make_device("a", primary_ip4="10.0.0.1", network_driver="cisco_ios")]),
        )

    device = _failed(outcomes, "a")
    assert device.errors[-1].code == "login_failed"
    assert device.errors[-1].failure is not None
    assert device.parsed["node-1"]["login"]["error"] == "session_not_alive"


@pytest.mark.asyncio
async def test_login_always_answers_both_handles_and_counts() -> None:
    with _login_netmiko(AsyncMock(return_value=True)):
        outcomes = await call_step(
            login_execute,
            _LOGIN_CONFIG,
            make_context([make_device("a", primary_ip4="10.0.0.1", network_driver="cisco_ios")]),
        )

    assert [o.name for o in outcomes] == ["success", "failure"]
    assert outcomes[1].context.devices == {}
    assert outcomes[0].context.metadata["node-1.login_counts"] == {"success": 1, "failure": 0}


@pytest.mark.asyncio
async def test_login_missing_host_records_missing_host_in_the_bag() -> None:
    device = make_device("a", hostname="", name="a").model_copy(
        update={"hostname": None, "primary_ip4": None}
    )
    with _login_netmiko(AsyncMock(return_value=True)):
        outcomes = await call_step(login_execute, _LOGIN_CONFIG, make_context([device]))

    failed = _failed(outcomes, "a")
    assert failed.errors[-1].code == "missing_host"
    assert failed.errors[-1].failure is not None
    assert failed.errors[-1].failure.kind == "bad_request"
    assert failed.parsed["node-1"]["login"]["error"] == "missing_host"


@pytest.mark.asyncio
async def test_login_logs_one_line_per_device(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO), _login_netmiko(AsyncMock(return_value=True)):
        await call_step(
            login_execute,
            _LOGIN_CONFIG,
            make_context([make_device("a", primary_ip4="10.0.0.1", network_driver="cisco_ios")]),
        )

    assert "login-successful device 1/1 id=a host=10.0.0.1: connecting" in caplog.text
    assert "login-successful device 1/1 id=a host=10.0.0.1: ok" in caplog.text


# --- reachable -----------------------------------------------------------------------------


def _ping(received: int = 4, sent: int = 4) -> MagicMock:
    result = MagicMock()
    result.packets_sent = sent
    result.packets_received = received
    result.avg_rtt = 1.0
    return result


@pytest.mark.asyncio
async def test_reachable_hides_the_text_of_a_library_error() -> None:
    with patch(f"{_REACH}.async_ping", AsyncMock(side_effect=ICMPLibError(_SECRET))):
        outcomes = await call_step(
            reachable_execute, {}, make_context([make_device("a", primary_ip4="10.0.0.1")])
        )

    error = _failed(outcomes, "a").errors[-1]
    assert error.code == "ping_error"
    assert _SECRET not in error.message
    assert error.failure is not None
    assert error.failure.kind == "no_route"


@pytest.mark.asyncio
async def test_reachable_name_lookup_error_is_a_dns_failure() -> None:
    with patch(f"{_REACH}.async_ping", AsyncMock(side_effect=NameLookupError("nope.invalid"))):
        outcomes = await call_step(
            reachable_execute, {}, make_context([make_device("a", primary_ip4="10.0.0.1")])
        )

    assert _failed(outcomes, "a").errors[-1].failure.kind == "dns"


@pytest.mark.asyncio
async def test_reachable_unexpected_error_fails_only_that_device() -> None:
    async def ping(host, **kwargs):
        if host == "10.0.0.2":
            raise OSError(_SECRET)
        return _ping()

    devices = [make_device("a", primary_ip4="10.0.0.1"), make_device("b", primary_ip4="10.0.0.2")]
    with patch(f"{_REACH}.async_ping", AsyncMock(side_effect=ping)):
        outcomes = await call_step(reachable_execute, {}, make_context(devices))

    by_name = {o.name: o for o in outcomes}
    assert set(by_name["success"].context.devices) == {"a"}
    error = by_name["failure"].context.devices["b"].errors[-1]
    assert error.message == "OSError"
    assert error.failure is not None


@pytest.mark.asyncio
async def test_reachable_unreachable_and_missing_host_carry_failure_records() -> None:
    no_host = make_device("n").model_copy(update={"hostname": None, "primary_ip4": None})
    devices = [make_device("a", primary_ip4="10.0.0.1"), no_host]
    with patch(f"{_REACH}.async_ping", AsyncMock(return_value=_ping(received=0))):
        outcomes = await call_step(reachable_execute, {}, make_context(devices))

    failure = next(o for o in outcomes if o.name == "failure").context.devices
    unreachable = failure["a"].errors[-1]
    assert unreachable.code == "unreachable"
    assert unreachable.failure is not None
    assert unreachable.failure.kind == "timeout"
    assert failure["n"].errors[-1].code == "missing_host"
    assert failure["n"].errors[-1].failure is not None
    # The result record of an unreachable host stays on the device.
    assert failure["a"].parsed["node-1"]["reachability"]["reachable"] is False


@pytest.mark.asyncio
async def test_reachable_pings_at_most_the_cap_at_once() -> None:
    in_flight = 0
    peak = 0

    async def ping(host, **kwargs):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        in_flight -= 1
        return _ping()

    devices = [
        make_device(f"d{n}", primary_ip4=f"10.0.{n // 250}.{n % 250 + 1}") for n in range(120)
    ]
    with patch(f"{_REACH}.async_ping", AsyncMock(side_effect=ping)):
        outcomes = await call_step(reachable_execute, {}, make_context(devices))

    assert len(outcomes[0].context.devices) == 120
    assert peak == MAX_CONCURRENT_PINGS


@pytest.mark.asyncio
async def test_reachable_validates_its_config_before_the_empty_guard() -> None:
    with pytest.raises(ValueError, match="ping_count"):
        await call_step(reachable_execute, {"ping_count": 0}, make_context([]))


@pytest.mark.asyncio
async def test_reachable_still_answers_both_handles_for_no_devices() -> None:
    outcomes = await call_step(reachable_execute, {}, make_context([]))

    assert [o.name for o in outcomes] == ["success", "failure"]
    assert outcomes[0].context.metadata == {}  # an empty input is a no-op, no counts
