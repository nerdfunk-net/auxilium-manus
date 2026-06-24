"""Deterministic WorkflowContext merge (see doc/MANUS_BASIS_DATATYPE.md)."""

from __future__ import annotations

from typing import Any

from models.workflow_context import (
    ArtifactRef,
    CommandResult,
    DeviceContext,
    DeviceError,
    WorkflowContext,
    worst_device_status,
)

_IDENTITY_SCALAR_FIELDS = (
    "id",
    "name",
    "hostname",
    "platform",
    "network_driver",
    "primary_ip4",
    "source",
    "source_id",
)


def merge_workflow_contexts(contexts: list[WorkflowContext]) -> WorkflowContext:
    """Merge parent contexts when branches converge."""
    if not contexts:
        raise ValueError("merge_workflow_contexts requires at least one context")

    base = contexts[0]
    for other in contexts[1:]:
        _assert_same_invariants(base, other)
        base = _merge_two_contexts(base, other)

    return base


def flatten_pending_commands(
    pending_by_node: dict[str, list[str]],
    node_order: list[str],
) -> list[str]:
    """Flatten per-device pending commands in topological node order."""
    flattened: list[str] = []
    for node_id in node_order:
        commands = pending_by_node.get(node_id)
        if commands:
            flattened.extend(commands)
    return flattened


def _assert_same_invariants(left: WorkflowContext, right: WorkflowContext) -> None:
    if left.run_id != right.run_id:
        raise ValueError("Cannot merge contexts with different run_id")
    if left.workflow_id != right.workflow_id:
        raise ValueError("Cannot merge contexts with different workflow_id")
    if left.schema_version != right.schema_version:
        raise ValueError("Cannot merge contexts with different schema_version")


def _merge_two_contexts(left: WorkflowContext, right: WorkflowContext) -> WorkflowContext:
    device_ids = set(left.devices) | set(right.devices)
    merged_devices: dict[str, DeviceContext] = {}
    for device_id in device_ids:
        left_device = left.devices.get(device_id)
        right_device = right.devices.get(device_id)
        if left_device is None:
            merged_devices[device_id] = right_device  # type: ignore[assignment]
        elif right_device is None:
            merged_devices[device_id] = left_device
        else:
            merged_devices[device_id] = merge_device_contexts([left_device, right_device])

    return left.model_copy(
        update={
            "devices": merged_devices,
            "pending_commands": _merge_pending_commands(
                left.pending_commands,
                right.pending_commands,
            ),
            "metadata": _merge_metadata(left.metadata, right.metadata),
        }
    )


def merge_device_contexts(devices: list[DeviceContext]) -> DeviceContext:
    if not devices:
        raise ValueError("merge_device_contexts requires at least one device")
    if len(devices) == 1:
        return devices[0]

    result = devices[0]
    for other in devices[1:]:
        result = _merge_two_devices(result, other)
    return result


def _merge_two_devices(left: DeviceContext, right: DeviceContext) -> DeviceContext:
    updates: dict[str, Any] = {}
    extra_errors: list[DeviceError] = []

    for field_name in _IDENTITY_SCALAR_FIELDS:
        left_value = getattr(left, field_name)
        right_value = getattr(right, field_name)
        merged_value, conflict_error = _merge_scalar_identity(left_value, right_value)
        updates[field_name] = merged_value
        if conflict_error is not None:
            extra_errors.append(conflict_error)

    updates["attributes"] = _merge_shallow_dicts(
        left.attributes,
        right.attributes,
        label="attributes",
    )
    updates["parsed"] = _merge_shallow_dicts(left.parsed, right.parsed, label="parsed")
    updates["running_config_ref"] = _merge_artifact_ref(
        left.running_config_ref,
        right.running_config_ref,
    )
    updates["startup_config_ref"] = _merge_artifact_ref(
        left.startup_config_ref,
        right.startup_config_ref,
    )
    updates["command_results"] = _merge_command_results(left.command_results, right.command_results)
    updates["capabilities"] = left.capabilities | right.capabilities
    updates["status"] = worst_device_status(left.status, right.status)
    updates["errors"] = _merge_errors(left.errors, [*right.errors, *extra_errors])

    return left.model_copy(update=updates)


def _merge_scalar_identity(
    left: Any,
    right: Any,
) -> tuple[Any, DeviceError | None]:
    if left == right or right is None:
        return left, None
    if left is None:
        return right, None
    return left, DeviceError(
        node_id="",
        step_id="merge",
        code="identity_conflict",
        message=f"Conflicting identity values during merge: {left!r} vs {right!r}",
    )


def _merge_shallow_dicts(
    left: dict[str, Any],
    right: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if key in merged and merged[key] != value:
            raise ValueError(f"Conflict merging {label} key {key!r}")
        merged[key] = value
    return merged


def _merge_artifact_ref(left: ArtifactRef | None, right: ArtifactRef | None) -> ArtifactRef | None:
    if left is None:
        return right
    if right is None:
        return left
    if left != right:
        raise ValueError("Conflict merging artifact refs with different values")
    return left


def _merge_command_results(
    left: dict[str, list[CommandResult]],
    right: dict[str, list[CommandResult]],
) -> dict[str, list[CommandResult]]:
    merged = dict(left)
    for node_id, results in right.items():
        if node_id in merged and merged[node_id] != results:
            raise ValueError(f"Conflict merging command_results for node_id {node_id!r}")
        merged[node_id] = results
    return merged


def _merge_errors(left: list[DeviceError], right: list[DeviceError]) -> list[DeviceError]:
    seen = {(error.node_id, error.step_id) for error in left}
    merged = list(left)
    for error in right:
        key = (error.node_id, error.step_id)
        if key in seen:
            continue
        merged.append(error)
        seen.add(key)
    return merged


def _merge_pending_commands(
    left: dict[str, dict[str, list[str]]],
    right: dict[str, dict[str, list[str]]],
) -> dict[str, dict[str, list[str]]]:
    merged: dict[str, dict[str, list[str]]] = {}
    for device_id in set(left) | set(right):
        left_per_device = left.get(device_id, {})
        right_per_device = right.get(device_id, {})
        merged[device_id] = _merge_pending_commands_for_device(left_per_device, right_per_device)
    return merged


def _merge_pending_commands_for_device(
    left: dict[str, list[str]],
    right: dict[str, list[str]],
) -> dict[str, list[str]]:
    merged = dict(left)
    for node_id, commands in right.items():
        if node_id in merged and merged[node_id] != commands:
            raise ValueError(f"Conflict merging pending_commands for node_id {node_id!r}")
        merged[node_id] = commands
    return merged


def _merge_metadata(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = dict(left)
    for key, value in right.items():
        if key in merged and merged[key] != value:
            raise ValueError(f"Conflict merging metadata key {key!r}")
        merged[key] = value
    return merged
