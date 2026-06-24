"""Tests for workflow context models and serialization."""

from __future__ import annotations

import json
import unittest

from pydantic import ValidationError

from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceStatus,
    WorkflowContext,
    bare_hostname,
)


class WorkflowContextModelTests(unittest.TestCase):
    def test_provided_capabilities_intersection(self) -> None:
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "a": DeviceContext(
                    id="a",
                    name="a",
                    hostname="10.0.0.1",
                    capabilities={Capability.IDENTITY, Capability.RUNNING_CONFIG},
                ),
                "b": DeviceContext(
                    id="b",
                    name="b",
                    hostname="10.0.0.2",
                    capabilities={Capability.IDENTITY},
                ),
            },
        )
        self.assertEqual(context.provided_capabilities(), {Capability.IDENTITY})

    def test_provided_capabilities_empty_inventory(self) -> None:
        context = WorkflowContext(run_id="run-1", workflow_id="wf-1")
        self.assertEqual(context.provided_capabilities(), set(Capability))

    def test_provided_parsed_keys_intersection(self) -> None:
        context = WorkflowContext(
            run_id="run-1",
            workflow_id="wf-1",
            devices={
                "a": DeviceContext(
                    id="a",
                    name="a",
                    hostname="10.0.0.1",
                    parsed={"bgp": {}, "vlans": []},
                ),
                "b": DeviceContext(
                    id="b",
                    name="b",
                    hostname="10.0.0.2",
                    parsed={"bgp": {}},
                ),
            },
        )
        self.assertEqual(context.provided_parsed_keys(), {"bgp"})

    def test_capabilities_json_round_trip(self) -> None:
        device = DeviceContext(
            id="a",
            name="a",
            hostname="10.0.0.1",
            capabilities={Capability.PARSED, Capability.IDENTITY},
        )
        payload = device.model_dump(mode="json")
        self.assertEqual(payload["capabilities"], ["identity", "parsed"])

        restored = DeviceContext.model_validate(json.loads(json.dumps(payload)))
        self.assertEqual(restored.capabilities, {Capability.IDENTITY, Capability.PARSED})

    def test_bare_hostname_strips_cidr(self) -> None:
        self.assertEqual(bare_hostname("192.168.1.1/24", "fallback"), "192.168.1.1")
        self.assertEqual(bare_hostname(None, "router1"), "router1")

    def test_extra_fields_forbidden(self) -> None:
        with self.assertRaises(ValidationError):
            DeviceContext(
                id="a",
                name="a",
                hostname="10.0.0.1",
                status=DeviceStatus.OK,
                unknown_field=True,  # type: ignore[call-arg]
            )


if __name__ == "__main__":
    unittest.main()
