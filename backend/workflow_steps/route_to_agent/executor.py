"""Executor for the route-to-agent step.

Sends the attributes and content the user selected, per device, to an agent handler and writes
the declared keys of its JSON answer under ``destination_path``. The agent is an enrichment
source only: it cannot choose an outcome, write outside the destination or return keys that were
not declared. See doc/AGENT_INTEGRATION.md.

Configuration errors raise ``ValueError`` and fail the step. A per-device problem (agent error,
timeout, an answer that breaks the output contract, a sealed secret among the inputs) routes that
device to ``failure``. If the agent as a whole is unreachable or rejects our secret, devices not
yet sent fail at once with the same cause instead of waiting out a timeout each.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.agents.exceptions import AgentAuthError, AgentOfflineError
from services.agents.source_config_service import AgentConnection
from services.artifacts import ArtifactService
from workflow_steps.common.agent_source import resolve_agent_connection
from workflow_steps.common.attribute_write import set_device_attribute
from workflow_steps.common.partial_outcomes import fail_device_with_error
from workflow_steps.route_to_agent.output import check_output, describe_failure
from workflow_steps.route_to_agent.request import (
    STEP_ID,
    InputRefusedError,
    StepConfig,
    build_inputs,
    parse_config,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

# Failures that say the agent as a whole is unusable: no point sending the remaining devices.
_SYSTEMIC = (AgentOfflineError, AgentAuthError)


class _Run:
    """What the concurrent device tasks share."""

    def __init__(self) -> None:
        self.abort: Exception | None = None


def _error(node_id: str, code: str, message: str, failure: FailureInfo) -> DeviceError:
    return DeviceError(
        node_id=node_id, step_id=STEP_ID, code=code, message=message, failure=failure
    )


async def _process(
    *,
    device: DeviceContext,
    config: StepConfig,
    client: Any,
    artifact_service: ArtifactService,
    node_id: str,
    shared: _Run,
    gate: asyncio.Semaphore,
) -> tuple[DeviceContext, bool]:
    async with gate:
        try:
            if shared.abort is not None:
                raise shared.abort
            try:
                inputs = await build_inputs(device, config, artifact_service)
            except InputRefusedError as exc:
                failure = FailureInfo(phase="agent", kind="bad_request", hint="check_request")
                return fail_device_with_error(
                    device, _error(node_id, exc.code, str(exc), failure)
                ), False
            output = await client.invoke(
                config.handler, config.params, inputs, timeout=config.timeout_seconds
            )
            checked = check_output(
                output, output_keys=config.output_keys, allow_missing=config.allow_missing_outputs
            )
            enriched = set_device_attribute(device, config.destination_path, dict(checked))
            return enriched.model_copy(update={"status": DeviceStatus.OK}), True
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if isinstance(exc, _SYSTEMIC) and shared.abort is None:
                shared.abort = exc
            code, message, failure = describe_failure(exc)
            if code == "internal_error":
                logger.exception(
                    "%s unexpected error node_id=%s device=%s", STEP_ID, node_id, device.id
                )
            return fail_device_with_error(device, _error(node_id, code, message, failure)), False


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del device_sessions

    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    parsed = parse_config(config)
    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{STEP_ID}: WorkflowRun has no active DB session")
    connection: AgentConnection = resolve_agent_connection(
        db, parsed.agent_source_id, step_id=STEP_ID
    )

    if parsed.timeout_seconds > connection.max_timeout_seconds:
        # Not clamped silently: a step set to 120 s against a 60 s agent would fail every device
        # at 60 s as "agent_timeout" with nothing pointing at the setting.
        raise ValueError(
            f"{STEP_ID}: timeout_seconds ({parsed.timeout_seconds}) is above the maximum of "
            f"{connection.max_timeout_seconds} seconds set on agent {connection.source_id!r}; "
            "lower the step timeout or raise the agent's max timeout in Settings -> Sources"
        )

    logger.info(
        "%s started run_id=%s node_id=%s agent=%s transport=%s handler=%s devices=%d",
        STEP_ID,
        context.run_id,
        node_id,
        connection.source_id,
        connection.transport,
        parsed.handler,
        len(context.devices),
    )

    shared = _Run()
    gate = asyncio.Semaphore(connection.max_concurrency)
    client = service_factory.build_agent_client(connection)
    try:
        results = await asyncio.gather(
            *[
                _process(
                    device=device,
                    config=parsed,
                    client=client,
                    artifact_service=artifact_service,
                    node_id=node_id,
                    shared=shared,
                    gate=gate,
                )
                for device in context.devices.values()
            ]
        )
    finally:
        await client.aclose()

    succeeded: dict[str, DeviceContext] = {}
    failed: dict[str, DeviceContext] = {}
    for device_id, (device, ok) in zip(context.devices, results, strict=True):
        (succeeded if ok else failed)[device_id] = device

    logger.info(
        "%s finished node_id=%s succeeded=%d failed=%d",
        STEP_ID,
        node_id,
        len(succeeded),
        len(failed),
    )
    metadata = {
        **context.metadata,
        f"{node_id}.agent": connection.source_id,
        f"{node_id}.succeeded": len(succeeded),
        f"{node_id}.failed": len(failed),
    }
    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": succeeded, "metadata": metadata}),
        )
    ]
    if failed:
        outcomes.append(
            StepOutcome(
                name="failure",
                context=context.model_copy(update={"devices": failed, "metadata": metadata}),
            )
        )
    return outcomes
