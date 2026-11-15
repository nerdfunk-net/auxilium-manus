import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import AsyncMock, patch

from manus_agent.fping import HostResult
from manus_agent.registry import HandlerRegistry

HANDLERS = Path(__file__).resolve().parents[1] / "handlers"


def load() -> HandlerRegistry:
    registry = HandlerRegistry()
    registry.load_directory(HANDLERS)  # re-imports the files: config.yaml is read here
    return registry


class ListDevicesHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_handler_is_registered_and_runs(self) -> None:
        func = load().get("list_devices")
        assert func is not None
        with (
            patch(
                "manus_agent.inventory.fetch_prefixes_by_tag",
                AsyncMock(return_value=["192.168.178.0/30"]),
            ),
            patch(
                "manus_agent.inventory.run_fping",
                AsyncMock(return_value=[HostResult("192.168.178.1", True, 0.3, 0)]),
            ),
        ):
            answer = await func({}, {"attributes": {"tag": "ping"}, "content": {}})
        assert answer == {
            "devices": [
                {"name": "192.168.178.1", "ip_address": "192.168.178.1", "network_driver": ""}
            ]
        }

    def test_a_bad_config_stops_loading_with_the_reason_on_stderr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "config.yaml"
            bad.write_text("nautobot:\n  url: ftp://x\n  token: t\n")
            stderr = io.StringIO()
            with (
                patch.dict(os.environ, {"MANUS_AGENT_CONFIG": str(bad)}),
                redirect_stderr(stderr),
                self.assertRaises(RuntimeError),
            ):
                load()
        assert "nautobot.url" in stderr.getvalue()
