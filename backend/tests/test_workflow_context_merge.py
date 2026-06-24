"""Tests for WorkflowContext merge behaviour."""

from __future__ import annotations

import unittest

from models.workflow_context import (
    ArtifactRef,
    Capability,
    CommandResult,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    WorkflowContext,
)
from services.workflow_context.merge import (
    flatten_pending_commands,
    merge_workflow_contexts,
)


def _device(
    device_id: str,
    *,
    capabilities: set[Capability] | None = None,
    status: DeviceStatus = DeviceStatus.OK,
) -> DeviceContext:
    return DeviceContext(
        id=device_id,
        name=device_id,
        hostname=f"10.0.0.{device_id}",
        capabilities=capabilities or {Capability.IDENTITY},
        status=status,
    )


def _context(
    *,
    devices: dict[str, DeviceContext] | None = None,
    pending_commands: dict[str, dict[str, list[str]]] | None = None,
) -> WorkflowContext:
    return WorkflowContext(
        run_id="run-1",
        workflow_id="wf-1",
        devices=devices or {},
        pending_commands=pending_commands or {},
    )


class WorkflowContextMergeTests(unittest.TestCase):
    def test_diamond_pending_commands_idempotent(self) -> None:
        ancestor_pending = {"device-1": {"node-a": ["interface Gi0/1"]}}
        left = _context(
            devices={"device-1": _device("device-1")},
            pending_commands=ancestor_pending,
        )
        right = _context(
            devices={"device-1": _device("device-1")},
            pending_commands=ancestor_pending,
        )
        merged = merge_workflow_contexts([left, right])
        self.assertEqual(merged.pending_commands, ancestor_pending)

    def test_pending_commands_conflict_raises(self) -> None:
        left = _context(pending_commands={"device-1": {"node-a": ["cmd-a"]}})
        right = _context(pending_commands={"device-1": {"node-a": ["cmd-b"]}})
        with self.assertRaises(ValueError):
            merge_workflow_contexts([left, right])

    def test_device_capabilities_union(self) -> None:
        left = _context(
            devices={
                "device-1": _device(
                    "device-1",
                    capabilities={Capability.IDENTITY, Capability.RUNNING_CONFIG},
                )
            }
        )
        right = _context(
            devices={
                "device-1": _device(
                    "device-1",
                    capabilities={Capability.IDENTITY, Capability.PARSED},
                )
            }
        )
        merged = merge_workflow_contexts([left, right])
        self.assertEqual(
            merged.devices["device-1"].capabilities,
            {Capability.IDENTITY, Capability.RUNNING_CONFIG, Capability.PARSED},
        )

    def test_status_worst_case_wins(self) -> None:
        left = _context(devices={"device-1": _device("device-1", status=DeviceStatus.OK)})
        right = _context(devices={"device-1": _device("device-1", status=DeviceStatus.FAILED)})
        merged = merge_workflow_contexts([left, right])
        self.assertEqual(merged.devices["device-1"].status, DeviceStatus.FAILED)

    def test_errors_deduped_by_node_and_step(self) -> None:
        error = DeviceError(node_id="n1", step_id="get-running-config", code="timeout", message="x")
        left = _context(
            devices={
                "device-1": _device("device-1").model_copy(update={"errors": [error]}),
            }
        )
        right = _context(
            devices={
                "device-1": _device("device-1").model_copy(update={"errors": [error]}),
            }
        )
        merged = merge_workflow_contexts([left, right])
        self.assertEqual(len(merged.devices["device-1"].errors), 1)

    def test_identity_conflict_records_error(self) -> None:
        left_device = _device("device-1").model_copy(update={"name": "left"})
        right_device = _device("device-1").model_copy(update={"name": "right"})
        left = _context(devices={"device-1": left_device})
        right = _context(devices={"device-1": right_device})
        merged = merge_workflow_contexts([left, right])
        self.assertEqual(merged.devices["device-1"].name, "left")
        errors = merged.devices["device-1"].errors
        self.assertTrue(any(error.code == "identity_conflict" for error in errors))

    def test_artifact_ref_conflict_raises(self) -> None:
        ref_a = ArtifactRef(artifact_id="a", kind="running_config")
        ref_b = ArtifactRef(artifact_id="b", kind="running_config")
        left = _context(
            devices={
                "device-1": _device("device-1").model_copy(update={"running_config_ref": ref_a}),
            }
        )
        right = _context(
            devices={
                "device-1": _device("device-1").model_copy(update={"running_config_ref": ref_b}),
            }
        )
        with self.assertRaises(ValueError):
            merge_workflow_contexts([left, right])

    def test_command_results_idempotent(self) -> None:
        results = {
            "node-send": [
                CommandResult(node_id="node-send", command="show version", success=True),
            ]
        }
        left = _context(
            devices={
                "device-1": _device("device-1").model_copy(update={"command_results": results}),
            }
        )
        right = _context(
            devices={
                "device-1": _device("device-1").model_copy(update={"command_results": results}),
            }
        )
        merged = merge_workflow_contexts([left, right])
        self.assertEqual(merged.devices["device-1"].command_results, results)

    def test_flatten_pending_commands_topological_order(self) -> None:
        pending = {
            "node-b": ["b-cmd"],
            "node-a": ["a-cmd"],
        }
        flattened = flatten_pending_commands(pending, ["node-a", "node-b"])
        self.assertEqual(flattened, ["a-cmd", "b-cmd"])


if __name__ == "__main__":
    unittest.main()
