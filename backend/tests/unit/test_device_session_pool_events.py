"""DeviceSessionPool hands the bound run-event context to connect() as a callback.

contextvars do not propagate through ``run_in_executor``, so the pool must read
the context on the event-loop side and pass an explicit callback.
"""

from __future__ import annotations

import unittest
from typing import Any
from unittest.mock import patch

from services.execution.run_events_reporter import RunEventContext, bound_run_event_context
from services.network.netmiko.session_pool import DeviceSessionPool


class _FakeSession:
    last_on_event: Any = "unset"
    connect_kwargs: dict[str, Any] = {}

    def __init__(
        self, *, host: str, device_type: str, username: str, password: str, keepalive: int = 30
    ) -> None:
        self.host = host
        self.connected = False

    def connect(
        self, *, privileged: bool = True, retry: object | None = None, **kwargs: Any
    ) -> None:
        _FakeSession.connect_kwargs = dict(kwargs)
        _FakeSession.last_on_event = kwargs.get("on_event")
        callback = kwargs.get("on_event")
        if callback is not None:
            callback("connected", "info", f"Connected to {self.host}")
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def is_alive(self) -> bool:
        return self.connected

    def check_config_mode(self) -> bool:
        return False


def _run(pool: DeviceSessionPool):
    return pool.run_on_device(
        host="10.0.0.1",
        device_type="cisco_ios",
        credential_reference="cred",
        username="u",
        password="p",
        op=lambda session: "ok",
    )


class PoolRunEventTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        _FakeSession.last_on_event = "unset"
        _FakeSession.connect_kwargs = {}
        patcher = patch("services.network.netmiko.session_pool.NetmikoDeviceSession", _FakeSession)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.emitted: list[dict[str, Any]] = []
        emit = patch(
            "services.execution.run_events_reporter.emit_run_event",
            side_effect=lambda context, **kw: self.emitted.append({"context": context, **kw}),
        )
        emit.start()
        self.addCleanup(emit.stop)

    async def _check(self, *, pooling: bool) -> None:
        pool = DeviceSessionPool(enabled=pooling)
        self.addCleanup(lambda: None)
        ctx = RunEventContext(run_id=7, node_id="a", child_index=3)
        try:
            with bound_run_event_context(ctx):
                result = await _run(pool)
        finally:
            await pool.close()

        self.assertEqual(result, "ok")
        self.assertEqual(len(self.emitted), 1)
        event = self.emitted[0]
        self.assertEqual(event["context"], ctx)
        self.assertEqual(event["kind"], "connected")
        self.assertEqual(event["device_name"], "10.0.0.1")

    async def test_pooled_connect_receives_callback_bound_to_context_and_host(self) -> None:
        await self._check(pooling=True)

    async def test_disposable_connect_receives_callback_too(self) -> None:
        await self._check(pooling=False)

    async def test_no_bound_context_means_no_on_event_argument(self) -> None:
        pool = DeviceSessionPool(enabled=True)
        try:
            await _run(pool)
        finally:
            await pool.close()

        self.assertNotIn("on_event", _FakeSession.connect_kwargs)
        self.assertEqual(self.emitted, [])


if __name__ == "__main__":
    unittest.main()
