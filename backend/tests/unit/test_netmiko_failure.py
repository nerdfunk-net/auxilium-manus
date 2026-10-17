"""Failure classification: Netmiko/socket exceptions -> models.failure.FailureInfo."""

from __future__ import annotations

import errno
import socket
from unittest.mock import MagicMock, patch

import pytest
from netmiko.exceptions import (
    ConfigInvalidException,
    NetmikoAuthenticationException,
    NetmikoTimeoutException,
    ReadTimeout,
)
from paramiko.ssh_exception import SSHException

from models.failure import FailureInfo, failure_from_exception
from services.network.netmiko.connection import (
    NetmikoConnectionError,
    NetmikoDeviceSession,
    RetryPolicy,
)
from services.network.netmiko.failure import classify_netmiko_exception


def _chained(outer: Exception, cause: BaseException) -> Exception:
    outer.__cause__ = cause
    return outer


def _session() -> NetmikoDeviceSession:
    return NetmikoDeviceSession(
        host="10.0.0.1", device_type="cisco_ios", username="u", password="p"
    )


@pytest.mark.parametrize(
    ("exc", "kind", "retryable", "hint"),
    [
        (NetmikoTimeoutException("timed out"), "timeout", True, "check_reachability"),
        (NetmikoAuthenticationException("bad"), "auth_failed", False, "check_credentials"),
        (
            _chained(NetmikoTimeoutException("x"), ConnectionRefusedError()),
            "refused",
            False,
            "check_ssh_service",
        ),
        (
            _chained(NetmikoTimeoutException("x"), socket.gaierror(-2, "nope")),
            "dns",
            False,
            "check_hostname",
        ),
        (
            _chained(NetmikoTimeoutException("x"), OSError(errno.EHOSTUNREACH, "unreachable")),
            "no_route",
            True,
            "check_reachability",
        ),
        (
            NetmikoTimeoutException("[Errno 111] Connection refused"),
            "refused",
            False,
            "check_ssh_service",
        ),
        (SSHException("Incompatible ssh server"), "ssh_error", False, "check_ssh_compatibility"),
        (RuntimeError("???"), "unknown", False, None),
    ],
)
def test_connect_phase(exc: Exception, kind: str, retryable: bool, hint: str | None) -> None:
    failure = classify_netmiko_exception(
        exc, phase="connect", attempts=2, max_attempts=3, elapsed_ms=5000
    )

    assert (failure.kind, failure.retryable, failure.hint) == (kind, retryable, hint)
    assert (failure.phase, failure.attempts, failure.max_attempts, failure.elapsed_ms) == (
        "connect",
        2,
        3,
        5000,
    )
    assert failure.exception_type == type(exc).__name__


def test_command_phase() -> None:
    assert classify_netmiko_exception(ReadTimeout("slow"), phase="command").kind == (
        "command_timeout"
    )
    assert classify_netmiko_exception(ConfigInvalidException("x"), phase="config").kind == (
        "config_rejected"
    )
    assert classify_netmiko_exception(ValueError("x"), phase="command").kind == "command_error"
    wrapped = _chained(RuntimeError("wrapper"), ReadTimeout("slow"))
    assert classify_netmiko_exception(wrapped, phase="command").kind == "command_timeout"


def test_exception_text_never_reaches_the_record() -> None:
    secret = "hunter2-SECRET"
    failure = classify_netmiko_exception(
        NetmikoAuthenticationException(f"password {secret} rejected"), phase="connect"
    )

    assert secret not in failure.model_dump_json()


def test_cause_chain_cycle_is_bounded() -> None:
    a, b = RuntimeError("a"), RuntimeError("b")
    a.__cause__, b.__cause__ = b, a

    assert classify_netmiko_exception(a, phase="connect").kind == "unknown"


def test_failure_from_exception() -> None:
    info = FailureInfo(phase="connect", kind="timeout")

    assert failure_from_exception(NetmikoConnectionError("x", failure=info)) is info
    assert failure_from_exception(NetmikoConnectionError("x")) is None
    assert failure_from_exception(ValueError("x")) is None


def test_session_connect_attaches_failure_with_attempt_count() -> None:
    session = _session()
    with (
        patch(
            "services.network.netmiko.connection.ConnectHandler",
            side_effect=NetmikoTimeoutException("t"),
        ) as handler,
        patch("services.network.netmiko.connection.time.sleep"),
        pytest.raises(NetmikoConnectionError) as info,
    ):
        session.connect(retry=RetryPolicy(backoff_seconds=(1, 2)))

    assert handler.call_count == 3
    failure = info.value.failure
    assert failure is not None
    assert (failure.phase, failure.kind, failure.attempts, failure.max_attempts) == (
        "connect",
        "timeout",
        3,
        3,
    )
    assert failure.elapsed_ms is not None


def test_session_connect_auth_failure_is_not_retried() -> None:
    session = _session()
    with (
        patch(
            "services.network.netmiko.connection.ConnectHandler",
            side_effect=NetmikoAuthenticationException("bad"),
        ) as handler,
        pytest.raises(NetmikoConnectionError) as info,
    ):
        session.connect(retry=RetryPolicy(backoff_seconds=(1, 2)))

    assert handler.call_count == 1
    assert info.value.failure is not None
    assert info.value.failure.kind == "auth_failed"
    assert info.value.failure.attempts == 1


def test_send_commands_result_carries_failure() -> None:
    session = _session()
    conn = MagicMock()
    conn.send_command.side_effect = ReadTimeout("slow")
    session._connection = conn

    result = session.send_commands(["show tech"])

    assert not result.success
    assert result.failure is not None
    assert result.failure.kind == "command_timeout"


def test_merge_running_config_failures_are_classified() -> None:
    session = _session()
    conn = MagicMock()
    conn.base_prompt = "r1"
    session._connection = conn

    conn.send_command.return_value = "%Error opening flash:x.cfg (No such file)"
    rejected = session.merge_running_config("flash:x.cfg")
    assert rejected.failure is not None
    assert (rejected.failure.phase, rejected.failure.kind) == ("config", "config_rejected")

    conn.send_command.side_effect = ReadTimeout("slow")
    timed_out = session.merge_running_config("flash:x.cfg")
    assert timed_out.failure is not None
    assert (timed_out.failure.phase, timed_out.failure.kind) == ("config", "command_timeout")


def test_upload_file_failure_uses_transfer_phase() -> None:
    session = _session()
    session._connection = MagicMock()

    with patch(
        "services.network.netmiko.connection.file_transfer", side_effect=OSError("scp denied")
    ):
        result = session.upload_file(local_path="/tmp/x", dest_file="x", file_system="flash:")

    assert result.failure is not None
    assert (result.failure.phase, result.failure.kind) == ("transfer", "command_error")


def test_login_successful_records_connect_failure() -> None:
    import asyncio

    from models.workflow_context import DeviceContext
    from workflow_steps.login_successful.executor import _try_login

    info = FailureInfo(phase="connect", kind="auth_failed", attempts=1, max_attempts=1)
    netmiko = MagicMock()

    async def _boom(**_: object) -> bool:
        raise NetmikoConnectionError("Authentication failed", failure=info)

    netmiko.test_login = _boom
    device = DeviceContext(id="d1", name="r1", hostname="r1", network_driver="cisco_ios")

    outcome, updated = asyncio.run(
        _try_login(
            device_id="d1",
            device=device,
            node_id="n1",
            credential_reference="c",
            network_driver_override=None,
            username="u",
            password="p",
            netmiko=netmiko,
        )
    )

    assert outcome == "failure"
    assert updated.errors[0].failure == info
