"""Tests for the generate-password executor.

The key property under test: the raw generated value must never appear in
plaintext in the step's metadata or logs — only as a sealed envelope in the
device's attribute bag (same "pipe-only" contract as secret-generate; see
doc/WORKFLOW-STEPS.md's Secret-valued attributes section).
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from models.workflow_context import Capability, DeviceContext, DeviceStatus, WorkflowContext
from services.workflow_context.secret_fields import is_sealed_secret, unwrap_secret
from workflow_steps.generate_password.executor import execute

BASE_CONFIG = {
    "length": 16,
    "min_digits": 2,
    "min_uppercase": 2,
    "min_lowercase": 2,
    "min_special": 2,
    "destination_path": "generated_password.value",
}


def _device(device_id: str) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=device_id,
        capabilities={Capability.IDENTITY},
        status=DeviceStatus.OK,
    )


def _context(devices: dict[str, DeviceContext]) -> WorkflowContext:
    return WorkflowContext(run_id="run-1", workflow_id="wf-1", devices=devices)


async def _run(config: dict, context: WorkflowContext):
    return await execute(
        config=config,
        context=context,
        run=MagicMock(),
        artifact_service=MagicMock(),
        node_id="node-1",
        device_sessions=MagicMock(),
    )


class GeneratePasswordExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_rejects_out_of_range_length(self) -> None:
        with self.assertRaises(ValueError):
            await _run({**BASE_CONFIG, "length": 4}, _context({}))

    async def test_rejects_minimums_exceeding_length(self) -> None:
        with self.assertRaises(ValueError):
            await _run(
                {**BASE_CONFIG, "length": 8, "min_digits": 5, "min_uppercase": 5},
                _context({}),
            )

    async def test_rejects_all_minimums_zero(self) -> None:
        with self.assertRaises(ValueError):
            await _run(
                {
                    **BASE_CONFIG,
                    "min_digits": 0,
                    "min_uppercase": 0,
                    "min_lowercase": 0,
                    "min_special": 0,
                },
                _context({}),
            )

    async def test_rejects_negative_minimum(self) -> None:
        with self.assertRaises(ValueError):
            await _run({**BASE_CONFIG, "min_digits": -1}, _context({}))

    async def test_missing_optional_keys_fall_back_to_config_py_defaults(self) -> None:
        context = _context({"d1": _device("d1")})
        outcomes = await _run({}, context)

        self.assertEqual([o.name for o in outcomes], ["success"])
        device = outcomes[0].context.devices["d1"]
        sealed = device.attribute_bags["generated_password"]["value"]
        self.assertTrue(is_sealed_secret(sealed))
        self.assertEqual(len(unwrap_secret(sealed) or ""), 16)

    async def test_empty_device_set_returns_trivial_success(self) -> None:
        outcomes = await _run(BASE_CONFIG, _context({}))
        self.assertEqual([o.name for o in outcomes], ["success"])
        self.assertEqual(outcomes[0].context.devices, {})

    async def test_per_device_generation_writes_sealed_value_at_destination_path(self) -> None:
        context = _context({"d1": _device("d1"), "d2": _device("d2")})
        outcomes = await _run(BASE_CONFIG, context)

        self.assertEqual([o.name for o in outcomes], ["success"])
        for device_id in ("d1", "d2"):
            device = outcomes[0].context.devices[device_id]
            sealed = device.attribute_bags["generated_password"]["value"]
            self.assertTrue(is_sealed_secret(sealed))
            self.assertEqual(len(unwrap_secret(sealed) or ""), 16)

    async def test_devices_get_independently_generated_values(self) -> None:
        context = _context({"d1": _device("d1"), "d2": _device("d2")})
        outcomes = await _run(BASE_CONFIG, context)

        d1_value = unwrap_secret(
            outcomes[0].context.devices["d1"].attribute_bags["generated_password"]["value"]
        )
        d2_value = unwrap_secret(
            outcomes[0].context.devices["d2"].attribute_bags["generated_password"]["value"]
        )
        self.assertNotEqual(d1_value, d2_value)

    async def test_generated_value_is_sealed_never_plaintext_in_metadata(self) -> None:
        context = _context({"d1": _device("d1")})
        outcomes = await _run(BASE_CONFIG, context)

        device = outcomes[0].context.devices["d1"]
        sealed = device.attribute_bags["generated_password"]["value"]
        plaintext = unwrap_secret(sealed)
        self.assertIsNotNone(plaintext)

        metadata_blob = json.dumps(outcomes[0].context.metadata)
        self.assertNotIn(plaintext, metadata_blob)
        self.assertEqual(outcomes[0].context.metadata["node-1.generated_count"], 1)

    async def test_custom_destination_path(self) -> None:
        context = _context({"d1": _device("d1")})
        outcomes = await _run({**BASE_CONFIG, "destination_path": "wifi.psk"}, context)

        device = outcomes[0].context.devices["d1"]
        sealed = device.attribute_bags["wifi"]["psk"]
        self.assertTrue(is_sealed_secret(sealed))


if __name__ == "__main__":
    unittest.main()
