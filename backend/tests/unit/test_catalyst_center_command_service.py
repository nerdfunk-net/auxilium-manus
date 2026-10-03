"""Tests for CatalystCenterCommandService: command runner flow and device config.

Response shapes are spec-derived (not yet verified against a live controller):
read-request -> {"response": {"taskId"}}; task -> {"response": {"progress": '{"fileId": ...}'}};
file -> [{"deviceUuid", "commandResponses": {"SUCCESS"|"FAILURE"|"BLOCKLISTED": {cmd: out}}}].
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock

from models.catalyst_center import CatalystCenterCommandStatus
from services.catalyst_center.command_service import CatalystCenterCommandService
from services.catalyst_center.common.exceptions import (
    CatalystCenterTaskError,
    CatalystCenterValidationError,
)
from services.catalyst_center.credentials import CatalystCenterCredentials

READ = "/dna/intent/api/v1/network-device-poller/cli/read-request"


def _creds() -> CatalystCenterCredentials:
    return CatalystCenterCredentials("https://10.10.20.85", "admin", "pw")


def _task(progress: str = "In progress", **extra) -> dict:
    return {"response": {"id": "task-1", "progress": progress, **extra}}


def _file(*entries: dict) -> list[dict]:
    return list(entries)


def _service(client: AsyncMock, **kwargs) -> CatalystCenterCommandService:
    return CatalystCenterCommandService(client, _creds(), poll_interval=0, max_polls=5, **kwargs)


class RunCommandsTests(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_submit_poll_fetch(self) -> None:
        client = AsyncMock()
        client.request.side_effect = [
            {"response": {"taskId": "task-1", "url": "/api/v1/task/task-1"}},
            _task("Preparing"),
            _task(json.dumps({"fileId": "file-9"})),
            _file(
                {
                    "deviceUuid": "uuid-1",
                    "commandResponses": {
                        "SUCCESS": {"show version": "Cisco IOS XE"},
                        "FAILURE": {"show bogus": "% Invalid input"},
                        "BLOCKLISTED": {"show tech": "blocked"},
                    },
                }
            ),
        ]
        results = await _service(client).run_commands(
            ["uuid-1"], ["show version", "show bogus", "show tech"], timeout=120
        )

        submit = client.request.await_args_list[0]
        self.assertEqual(submit.args[1:3], ("POST", READ))
        body = submit.kwargs["json"]
        self.assertEqual(body["commands"], ["show version", "show bogus", "show tech"])
        self.assertEqual(body["deviceUuids"], ["uuid-1"])
        self.assertEqual(body["timeout"], 120)
        self.assertEqual(
            client.request.await_args_list[1].args[2], "/dna/intent/api/v1/task/task-1"
        )
        self.assertEqual(
            client.request.await_args_list[3].args[2], "/dna/intent/api/v1/file/file-9"
        )

        by_cmd = {r.command: r for r in results}
        self.assertEqual(by_cmd["show version"].status, CatalystCenterCommandStatus.SUCCESS)
        self.assertEqual(by_cmd["show version"].output, "Cisco IOS XE")
        self.assertEqual(by_cmd["show version"].device_id, "uuid-1")
        self.assertEqual(by_cmd["show bogus"].status, CatalystCenterCommandStatus.FAILURE)
        self.assertEqual(by_cmd["show tech"].status, CatalystCenterCommandStatus.BLOCKLISTED)

    async def test_multiple_devices(self) -> None:
        client = AsyncMock()
        client.request.side_effect = [
            {"response": {"taskId": "t"}},
            _task(json.dumps({"fileId": "f"})),
            _file(
                {"deviceUuid": "a", "commandResponses": {"SUCCESS": {"show clock": "1"}}},
                {"deviceUuid": "b", "commandResponses": {"SUCCESS": {"show clock": "2"}}},
            ),
        ]
        results = await _service(client).run_commands(["a", "b"], ["show clock"])
        self.assertEqual({(r.device_id, r.output) for r in results}, {("a", "1"), ("b", "2")})

    async def test_task_error_raises_with_failure_reason(self) -> None:
        client = AsyncMock()
        client.request.side_effect = [
            {"response": {"taskId": "t"}},
            _task("failed", isError=True, failureReason="Device unreachable"),
        ]
        with self.assertRaises(CatalystCenterTaskError) as ctx:
            await _service(client).run_commands(["a"], ["show clock"])
        self.assertIn("Device unreachable", str(ctx.exception))

    async def test_poll_timeout_raises(self) -> None:
        client = AsyncMock()
        client.request.side_effect = [{"response": {"taskId": "t"}}] + [_task()] * 10
        with self.assertRaises(CatalystCenterTaskError) as ctx:
            await _service(client).run_commands(["a"], ["show clock"])
        self.assertIn("did not finish", str(ctx.exception))

    async def test_missing_task_id_raises(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": {}}
        with self.assertRaises(CatalystCenterTaskError):
            await _service(client).run_commands(["a"], ["show clock"])

    async def test_unsafe_task_id_rejected(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": {"taskId": "../../x"}}
        with self.assertRaises(CatalystCenterTaskError):
            await _service(client).run_commands(["a"], ["show clock"])

    async def test_non_list_file_raises(self) -> None:
        client = AsyncMock()
        client.request.side_effect = [
            {"response": {"taskId": "t"}},
            _task(json.dumps({"fileId": "f"})),
            {"oops": 1},
        ]
        with self.assertRaises(CatalystCenterTaskError):
            await _service(client).run_commands(["a"], ["show clock"])

    async def test_non_json_progress_keeps_polling(self) -> None:
        client = AsyncMock()
        client.request.side_effect = [
            {"response": {"taskId": "t"}},
            _task("not-json"),
            _task(json.dumps({"fileId": "f"})),
            _file({"deviceUuid": "a", "commandResponses": {"SUCCESS": {"show clock": "x"}}}),
        ]
        results = await _service(client).run_commands(["a"], ["show clock"])
        self.assertEqual(len(results), 1)


class InputValidationTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_empty_devices(self) -> None:
        client = AsyncMock()
        with self.assertRaises(CatalystCenterValidationError):
            await _service(client).run_commands([], ["show clock"])
        client.request.assert_not_called()

    async def test_rejects_empty_or_blank_commands(self) -> None:
        client = AsyncMock()
        for commands in ([], ["  "], [""]):
            with self.assertRaises(CatalystCenterValidationError):
                await _service(client).run_commands(["a"], commands)
        client.request.assert_not_called()

    async def test_rejects_unsafe_device_id(self) -> None:
        client = AsyncMock()
        with self.assertRaises(CatalystCenterValidationError):
            await _service(client).run_commands(["a/../b"], ["show clock"])

    async def test_rejects_out_of_range_timeout(self) -> None:
        client = AsyncMock()
        for timeout in (0, -1, 99999):
            with self.assertRaises(CatalystCenterValidationError):
                await _service(client).run_commands(["a"], ["show clock"], timeout=timeout)


class DeviceConfigTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_running_config_text(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": "hostname sw1\n!\nend"}
        config = await _service(client).get_device_config("uuid-1")
        self.assertEqual(config, "hostname sw1\n!\nend")
        self.assertEqual(
            client.request.await_args.args[1:3],
            ("GET", "/dna/intent/api/v1/network-device/uuid-1/config"),
        )

    async def test_non_string_config_rejected(self) -> None:
        client = AsyncMock()
        client.request.return_value = {"response": {"x": 1}}
        with self.assertRaises(CatalystCenterValidationError):
            await _service(client).get_device_config("uuid-1")

    async def test_unsafe_device_id_rejected(self) -> None:
        client = AsyncMock()
        with self.assertRaises(CatalystCenterValidationError):
            await _service(client).get_device_config("../etc")
        client.request.assert_not_called()
