"""The result-store block of the steps that push configuration lines over SSH (W3a-06).

``run-command`` (Run Command) in config mode and ``deploy-rendered-template`` (Deploy rendered
Template) turn one ``DeployResult`` into the same stored rows: the transcript, the raw session
log of a failure and the ``copy running-config startup-config`` save.
"""

from __future__ import annotations

from models.workflow_context import CommandResult
from services.artifacts import ArtifactService
from services.network.netmiko.connection import DeployResult

_SESSION_LOG_SUMMARY = (
    "Raw Netmiko session log captured up to the failure — inspect for confirmation prompts "
    "or unexpected CLI output that stalled pattern detection"
)


async def store_push_result(
    result: DeployResult,
    *,
    command_label: str,
    summary: str,
    device_id: str,
    node_id: str,
    context_run_id: str,
    artifact_service: ArtifactService,
) -> list[CommandResult]:
    """Store the transcript (and, when present, the session log and the save output) as rows.

    ``summary`` is the step's own sentence for the transcript row; the count of auto-confirmed
    prompts is appended here.
    """
    if result.confirmed_prompts:
        summary += f" · {len(result.confirmed_prompts)} confirmation prompt(s) auto-confirmed"

    rows = [
        CommandResult(
            node_id=node_id,
            command=command_label,
            success=result.success,
            output_ref=await artifact_service.store(
                content=result.config_output,
                kind="command_output",
                device_id=device_id,
                run_id=context_run_id,
            ),
            summary=summary,
        )
    ]
    if result.session_log:
        rows.append(
            CommandResult(
                node_id=node_id,
                command="netmiko-session-log",
                success=False,
                output_ref=await artifact_service.store(
                    content=result.session_log,
                    kind="netmiko_session_log",
                    device_id=device_id,
                    run_id=context_run_id,
                ),
                summary=_SESSION_LOG_SUMMARY,
            )
        )
    if result.save_output is not None:
        rows.append(
            CommandResult(
                node_id=node_id,
                command="copy running-config startup-config",
                success=True,
                output_ref=await artifact_service.store(
                    content=result.save_output,
                    kind="command_output",
                    device_id=device_id,
                    run_id=context_run_id,
                ),
                summary="running-config saved to startup-config",
            )
        )
    return rows
