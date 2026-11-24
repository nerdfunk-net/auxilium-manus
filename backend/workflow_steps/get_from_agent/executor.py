"""Executor for the get-from-agent step.

Sends the configured attributes to a handler on an agent and builds the workflow's devices from
the list it returns (``{"devices": [{name, ip_address, network_driver}, ...]}``, the same rows
as ``get-from-list``). An inventory that is wrong or incomplete is worse than none, so every
problem - agent unreachable, handler error, a malformed answer, an invalid row, an empty list -
fails the step. See doc/AGENT_INTEGRATION.md.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from core.safe_hosts import validate_device_host
from models.workflow_context import StepOutcome, WorkflowContext
from services.agents.exceptions import AgentCallError
from services.agents.failure import describe_call_failure
from services.agents.source_config_service import AgentConnection
from services.artifacts import ArtifactService
from workflow_steps.common.agent_source import resolve_agent_connection
from workflow_steps.common.device_list import (
    DeviceEntry,
    device_context_from_entry,
    normalize_device_entries,
)
from workflow_steps.common.fan_out import build_fan_out_metadata
from workflow_steps.common.run_logging import log_run_id
from workflow_steps.get_from_agent.request import STEP_ID, build_inputs, parse_config

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

MAX_DEVICES = 5000
# Names kept in the persisted ``{node_id}.devices`` list: the stored copy of a value above
# STEP_OUTPUT_VALUE_MAX_BYTES is replaced by a marker, so a full 5000-name list would be lost.
MAX_LISTED_NAMES = 500


def _device_rows(output: dict[str, Any]) -> list[Any]:
    extra = sorted(set(output) - {"devices"})
    if extra:
        raise RuntimeError(f"{STEP_ID}: the agent returned unexpected keys: {', '.join(extra)}")
    rows = output.get("devices")
    if not isinstance(rows, list):
        raise RuntimeError(f"{STEP_ID}: the agent answer needs a 'devices' list")
    if len(rows) > MAX_DEVICES:
        raise RuntimeError(f"{STEP_ID}: the agent returned more than {MAX_DEVICES} devices")
    for index, row in enumerate(rows, start=1):
        _check_row(row, index)
    return rows


def _check_row(row: Any, index: int) -> None:
    """A row must name its device: ``normalize_device_entries`` would silently drop a blank one,
    and a dropped row is a partial inventory."""
    if isinstance(row, str):
        values: list[Any] = [row]
    elif isinstance(row, dict):
        values = [row.get("name"), row.get("ip_address")]
        if any(
            v is not None and not isinstance(v, str) for v in (*values, row.get("network_driver"))
        ):
            raise RuntimeError(
                f"{STEP_ID}: device {index}: name, ip_address and driver must be text"
            )
    else:
        raise RuntimeError(f"{STEP_ID}: device {index} must be an object or a name")
    if not any(isinstance(v, str) and v.strip() for v in values):
        raise RuntimeError(f"{STEP_ID}: device {index} has neither a name nor an IP address")


def _check_hosts(entries: list[DeviceEntry]) -> None:
    """The agent chooses where the workflow's SSH credential goes: apply the host policy every
    inventory host gets (no loopback, link-local, unspecified or multicast, no metadata name)."""
    for index, entry in enumerate(entries, start=1):
        if entry.ip_address is not None:
            try:
                ipaddress.ip_address(entry.ip_address)  # rejects CIDR, 10.0.0.01, 999.x
            except ValueError as exc:
                raise ValueError(
                    f"{STEP_ID}: device {index}: ip_address must be a plain IP address"
                ) from exc
        for host in (entry.ip_address, entry.name):
            if host is None:
                continue
            try:
                validate_device_host(host)
            except ValueError as exc:
                raise ValueError(f"{STEP_ID}: device {index}: {exc}") from exc


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service, device_sessions

    parsed = parse_config(config)
    inputs = build_inputs(parsed, run.run_inputs)
    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{STEP_ID}: WorkflowRun has no active DB session")
    connection: AgentConnection = resolve_agent_connection(
        db, parsed.agent_source_id, step_id=STEP_ID
    )
    if parsed.timeout_seconds > connection.max_timeout_seconds:
        raise ValueError(
            f"{STEP_ID}: timeout_seconds ({parsed.timeout_seconds}) is above the maximum of "
            f"{connection.max_timeout_seconds} seconds set on agent {connection.source_id!r}; "
            "lower the step timeout or raise the agent's max timeout in Settings -> Sources"
        )

    logger.info(
        "%s started run_id=%s node_id=%s agent=%s transport=%s handler=%s attributes=%d",
        STEP_ID,
        log_run_id(run),
        node_id,
        connection.source_id,
        connection.transport,
        parsed.handler,
        len(parsed.attributes),
    )

    client = service_factory.build_agent_client(connection)
    try:
        output = await client.invoke(parsed.handler, {}, inputs, timeout=parsed.timeout_seconds)
    except AgentCallError as exc:
        _, message, _ = describe_call_failure(exc)
        raise RuntimeError(f"{STEP_ID}: {message}") from exc
    finally:
        await client.aclose()

    entries = normalize_device_entries(_device_rows(output), step=STEP_ID)
    if not entries:
        raise RuntimeError(f"{STEP_ID}: the agent returned no devices")
    _check_hosts(entries)

    new_devices = {
        device.id: device
        for index, entry in enumerate(entries)
        for device in [
            device_context_from_entry(
                entry,
                index=index,
                node_id=node_id,
                source="agent",
                attribute_bag_name="get_from_agent",
            )
        ]
    }

    metadata: dict[str, Any] = {
        **context.metadata,
        f"{node_id}.total": len(new_devices),
        f"{node_id}.devices": [device.name for device in new_devices.values()][:MAX_LISTED_NAMES],
        f"{node_id}.agent": connection.source_id,
    }
    fan_out_metadata = build_fan_out_metadata(config.get("fan_out"), node_id)
    if fan_out_metadata is not None:
        metadata["_fan_out"] = fan_out_metadata

    logger.info("%s finished run_id=%s devices=%d", STEP_ID, log_run_id(run), len(new_devices))
    new_context = context.model_copy(
        update={"devices": {**context.devices, **new_devices}, "metadata": metadata}
    )
    return [StepOutcome(name="success", context=new_context)]
