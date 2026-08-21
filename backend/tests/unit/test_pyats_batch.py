"""Tests for the shared pyATS shim batching helper."""

from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, MagicMock

from models.workflow_context import DeviceContext, DeviceStatus
from services.pyats.common.exceptions import PyATSAPIError
from services.pyats.credentials import PyATSCredentials
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.common.pyats_batch import (
    BASE_TIMEOUT_SECONDS,
    PER_DEVICE_TIMEOUT_SECONDS,
    run_batched,
    validate_and_group_devices,
)


def _device_with_testbed(device_id: str, *, source_id: str = "lab-pyats") -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        status=DeviceStatus.OK,
        attribute_bags={
            "pyats_testbed": {
                "pyats_source_id": source_id,
                "host": "10.0.0.1",
                "os": "ios",
                "username": "admin",
                "password": seal_secret("secret"),
            }
        },
    )


def _device_without_bag(device_id: str) -> DeviceContext:
    return DeviceContext(id=device_id, name=device_id, hostname=device_id, status=DeviceStatus.OK)


def _device_without_password(device_id: str, *, source_id: str = "lab-pyats") -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        status=DeviceStatus.OK,
        attribute_bags={
            "pyats_testbed": {
                "pyats_source_id": source_id,
                "host": "10.0.0.1",
                "os": "ios",
                "username": "admin",
                "password": None,
            }
        },
    )


def _credentials() -> PyATSCredentials:
    return PyATSCredentials(base_url="http://shim", token="tok")


class ValidateAndGroupDevicesTests(unittest.TestCase):
    def test_missing_bag_is_immediate_failure(self) -> None:
        groups, failures = validate_and_group_devices(
            devices={"device-1": _device_without_bag("device-1")},
            node_id="node-1",
            step_id="get-pyats-config",
            source_credentials={},
            source_errors={},
        )
        self.assertEqual(groups, {})
        self.assertEqual(failures["device-1"].errors[0].code, "missing_testbed")

    def test_missing_password_is_immediate_failure(self) -> None:
        groups, failures = validate_and_group_devices(
            devices={"device-1": _device_without_password("device-1")},
            node_id="node-1",
            step_id="get-pyats-config",
            source_credentials={"lab-pyats": _credentials()},
            source_errors={},
        )
        self.assertEqual(groups, {})
        self.assertEqual(failures["device-1"].errors[0].code, "missing_credential")

    def test_unresolvable_source_is_immediate_failure_and_excluded(self) -> None:
        groups, failures = validate_and_group_devices(
            devices={"device-1": _device_with_testbed("device-1", source_id="bad-source")},
            node_id="node-1",
            step_id="get-pyats-config",
            source_credentials={},
            source_errors={"bad-source": "no credential"},
        )
        self.assertEqual(groups, {})
        self.assertEqual(failures["device-1"].errors[0].code, "source_error")

    def test_groups_by_source(self) -> None:
        devices = {
            "device-1": _device_with_testbed("device-1", source_id="lab-a"),
            "device-2": _device_with_testbed("device-2", source_id="lab-a"),
            "device-3": _device_with_testbed("device-3", source_id="lab-b"),
        }
        groups, failures = validate_and_group_devices(
            devices=devices,
            node_id="node-1",
            step_id="get-pyats-config",
            source_credentials={"lab-a": _credentials(), "lab-b": _credentials()},
            source_errors={},
        )
        self.assertEqual(failures, {})
        self.assertEqual({d for d, _ in groups["lab-a"]}, {"device-1", "device-2"})
        self.assertEqual({d for d, _ in groups["lab-b"]}, {"device-3"})
        self.assertEqual(groups["lab-a"][0][1]["password"], "secret")


class RunBatchedTests(unittest.IsolatedAsyncioTestCase):
    def _credentials(self) -> PyATSCredentials:
        return PyATSCredentials(base_url="http://shim", token="tok")

    def _group(self, device_ids: list[str]) -> list[tuple[str, dict]]:
        return [(device_id, {"name": device_id, "host": "10.0.0.1"}) for device_id in device_ids]

    async def test_empty_group_makes_no_calls(self) -> None:
        shim = MagicMock()
        shim.run_job = AsyncMock()
        result = await run_batched(
            shim=shim,
            credentials=self._credentials(),
            operation="parse",
            commands=["show version"],
            device_group=[],
        )
        self.assertEqual(result, {})
        shim.run_job.assert_not_awaited()

    async def test_devices_under_chunk_size_make_one_call(self) -> None:
        shim = MagicMock()
        shim.run_job = AsyncMock(
            return_value={
                "results": {
                    "device-1": {"success": True, "error": None, "commands": {}},
                    "device-2": {"success": True, "error": None, "commands": {}},
                }
            }
        )
        result = await run_batched(
            shim=shim,
            credentials=self._credentials(),
            operation="parse",
            commands=["show version"],
            device_group=self._group(["device-1", "device-2"]),
            chunk_size=5,
        )
        shim.run_job.assert_awaited_once()
        call_kwargs = shim.run_job.call_args.kwargs
        self.assertEqual(len(call_kwargs["devices"]), 2)
        expected_timeout = BASE_TIMEOUT_SECONDS + PER_DEVICE_TIMEOUT_SECONDS * 2
        self.assertEqual(call_kwargs["timeout_seconds"], expected_timeout)
        self.assertEqual(set(result), {"device-1", "device-2"})

    async def test_devices_over_chunk_size_are_split(self) -> None:
        device_ids = [f"device-{i}" for i in range(12)]

        async def fake_run_job(_credentials, *, operation, devices, commands, timeout_seconds):
            return {
                "results": {
                    d["name"]: {"success": True, "error": None, "commands": {}} for d in devices
                }
            }

        shim = MagicMock()
        shim.run_job = AsyncMock(side_effect=fake_run_job)

        result = await run_batched(
            shim=shim,
            credentials=self._credentials(),
            operation="parse",
            commands=["show version"],
            device_group=self._group(device_ids),
            chunk_size=5,
        )
        self.assertEqual(shim.run_job.await_count, 3)
        chunk_sizes = sorted(
            len(call.kwargs["devices"]) for call in shim.run_job.await_args_list
        )
        self.assertEqual(chunk_sizes, [2, 5, 5])
        for call in shim.run_job.await_args_list:
            n = len(call.kwargs["devices"])
            expected_timeout = BASE_TIMEOUT_SECONDS + PER_DEVICE_TIMEOUT_SECONDS * n
            self.assertEqual(call.kwargs["timeout_seconds"], expected_timeout)
        self.assertEqual(set(result), set(device_ids))

    async def test_chunk_failure_fails_only_that_chunks_devices(self) -> None:
        call_count = 0

        async def fake_run_job(_credentials, *, operation, devices, commands, timeout_seconds):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise PyATSAPIError("boom")
            return {
                "results": {
                    d["name"]: {"success": True, "error": None, "commands": {}} for d in devices
                }
            }

        shim = MagicMock()
        shim.run_job = AsyncMock(side_effect=fake_run_job)

        device_ids = [f"device-{i}" for i in range(8)]
        result = await run_batched(
            shim=shim,
            credentials=self._credentials(),
            operation="parse",
            commands=["show version"],
            device_group=self._group(device_ids),
            chunk_size=5,
        )
        self.assertEqual(shim.run_job.await_count, 2)
        first_chunk_ids = {d for d, _ in self._group(device_ids)[:5]}
        second_chunk_ids = {d for d, _ in self._group(device_ids)[5:]}
        for device_id in first_chunk_ids:
            self.assertFalse(result[device_id]["success"])
            self.assertEqual(result[device_id]["error"], "boom")
        for device_id in second_chunk_ids:
            self.assertTrue(result[device_id]["success"])


if __name__ == "__main__":
    unittest.main()
