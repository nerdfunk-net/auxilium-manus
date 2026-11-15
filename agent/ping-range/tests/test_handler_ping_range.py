import io
import os
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import AsyncMock, patch

from manus_agent.fping import HostResult
from manus_agent.registry import HandlerRegistry

HANDLERS = Path(__file__).resolve().parents[1] / "handlers"


def load() -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.load_directory(HANDLERS)  # re-imports the files: the environment is read here
    return registry


class PingRangeHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_handler_is_registered_and_runs(self) -> None:
        func = load().get("ping_range")
        assert func is not None
        run = AsyncMock(return_value=[HostResult("10.0.0.1", True, 0.3, 0)])
        with patch("manus_agent.ping.run_fping", run):
            answer = await func({}, {"attributes": {"range": "10.0.0.1"}, "content": {}})
        assert answer["reachable"] == 1 and answer["hosts"][0]["ip"] == "10.0.0.1"

    async def test_operator_limits_come_from_the_environment(self) -> None:
        with patch.dict(os.environ, {"MANUS_AGENT_PING_ALLOWED_NETWORKS": "10.0.0.0/24"}):
            func = load().get("ping_range")
        assert func is not None
        with self.assertRaises(ValueError):
            await func({}, {"attributes": {"range": "192.168.0.1"}, "content": {}})

    async def test_the_default_is_private_networks_only(self) -> None:
        env = {k: v for k, v in os.environ.items() if k != "MANUS_AGENT_PING_ALLOWED_NETWORKS"}
        with patch.dict(os.environ, env, clear=True):
            func = load().get("ping_range")
        assert func is not None
        with self.assertRaises(ValueError) as caught:
            await func({}, {"attributes": {"range": "8.8.8.8"}, "content": {}})
        assert "allowed" in str(caught.exception)


class StartupValidationTests(unittest.TestCase):
    def test_a_bad_limit_stops_the_agent_at_startup_with_the_reason(self) -> None:
        for name in ("MANUS_AGENT_PING_MAX_HOSTS", "MANUS_AGENT_PING_ALLOWED_NETWORKS"):
            with self.subTest(name=name):
                stderr = io.StringIO()
                with (
                    patch.dict(os.environ, {name: "nonsense"}),
                    redirect_stderr(stderr),
                    self.assertRaises(RuntimeError),
                ):
                    load()
                assert name in stderr.getvalue()
