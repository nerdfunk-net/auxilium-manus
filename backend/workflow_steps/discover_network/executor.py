"""Executor for the discover-network step.

Starts at the devices that arrive in the context, reads ``show cdp neighbors detail`` over a
pooled SSH session, logs out and follows the neighbours that lie inside the permitted
prefixes, level by level (``crawler.crawl``). Every device that was logged into leaves on
``success`` (the seeds enriched, the discovered ones as new devices); a seed that could not be
visited leaves on ``failure``. Neighbours that were seen but not visited are listed in
``metadata["<node id>.discovery"]`` with the reason.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

from core.config import settings
from core.models.runs import WorkflowRun
from models.failure import FailureInfo, failure_from_exception
from models.workflow_context import (
    DeviceContext,
    StepOutcome,
    WorkflowContext,
    bare_hostname,
)
from services.artifacts import ArtifactService
from services.network.netmiko.platform import resolve_connection_device_type
from services.network.netmiko.service import NetmikoService
from workflow_steps.common.credential_resolver import resolve_ssh_credential
from workflow_steps.common.partial_outcomes import mark_device_failed
from workflow_steps.common.run_param_reference import resolve_config_reference
from workflow_steps.common.step_flags import record_dry_run
from workflow_steps.discover_network.crawler import (
    CrawlResult,
    CrawlSettings,
    Reading,
    Target,
    VisitError,
    crawl,
)
from workflow_steps.discover_network.options import STEP_ID, DiscoverOptions, parse_options
from workflow_steps.discover_network.parsing import (
    CDP_COMMAND,
    SUPPORTED_DEVICE_TYPES,
    CdpStatus,
    classify_cdp_output,
)
from workflow_steps.discover_network.results import (
    RESULT_KEY,
    device_summary,
    discovered_device,
    step_summary,
    with_discovery,
)
from workflow_steps.discover_network.scope import (
    check_discovered_host,
    ensure_following_allowed,
    in_scope,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_UNSUPPORTED = FailureInfo(phase="connect", kind="unsupported_platform", hint="check_platform")
_NO_CDP = FailureInfo(phase="command", kind="command_error")
_MESSAGES = {
    "unreachable": "The device could not be reached or its CDP neighbours could not be read",
    "login_failed": "The device rejected the login",
    "cdp_not_enabled": "CDP is not enabled on the device",
    "cdp_not_supported": "The device refused the CDP command",
    "cdp_no_output": "The device returned no CDP table (empty or unrecognised output)",
    "out_of_scope": "The address is outside the permitted prefixes or not allowed",
    "unsupported_platform": "Discover Network supports Cisco IOS, IOS-XE and NX-OS devices only",
    "missing_host": "The device has no hostname or primary IP",
}


# A seed that was reached but gave no CDP table: one code per cause the parser told apart.
_CDP_PROBLEM_CODES = {
    CdpStatus.NOT_ENABLED.value: "cdp_not_enabled",
    CdpStatus.NOT_SUPPORTED.value: "cdp_not_supported",
    CdpStatus.UNPARSEABLE.value: "cdp_no_output",
}


def _visit_code(failure: FailureInfo | None) -> str:
    return (
        "login_failed" if failure is not None and failure.kind == "auth_failed" else "unreachable"
    )


def _seed_target(device_id: str, device: DeviceContext, options: DiscoverOptions) -> Target:
    """The SSH target of a seed; raises ``VisitError`` when the device cannot be reached at all."""
    host = bare_hostname(device.primary_ip4, device.hostname)
    if not host:
        raise VisitError("missing_host")
    try:
        device_type = resolve_connection_device_type(
            network_driver=device.network_driver,
            platform=device.platform,
            override=options.network_driver_override,
        )
    except ValueError as exc:  # UnsupportedPlatformError
        raise VisitError(
            "unsupported_platform", failure_from_exception(exc) or _UNSUPPORTED
        ) from exc
    if device_type not in SUPPORTED_DEVICE_TYPES:
        raise VisitError("unsupported_platform", _UNSUPPORTED)
    return Target(
        name=device.name, host=host, device_type=device_type, depth=0,
        discovered_from=None, seed_id=device_id,
    )  # fmt: skip


def _fail(device: DeviceContext, node_id: str, error: VisitError) -> DeviceContext:
    return mark_device_failed(
        device,
        node_id=node_id,
        step_id=STEP_ID,
        code=error.code,
        message=_MESSAGES.get(error.code, "The device could not be visited"),
        failure=error.failure,
    )


def _followed_host_allowed(host: str, options: DiscoverOptions) -> bool:
    if not in_scope(host, options.prefixes):
        return False
    try:
        check_discovered_host(host)
    except ValueError:
        return False
    return True


def _make_visit(
    *,
    netmiko: NetmikoService,
    pool: DeviceSessionPool,
    credentials: tuple[str, str, str],
    options: DiscoverOptions,
):  # noqa: ANN202
    username, password, reference = credentials

    async def visit(target: Target) -> Reading:
        # The credential must never reach a host the policy refuses, whatever the crawler
        # decided: CDP is unauthenticated, so a followed host is checked again right before
        # the login. Seeds come from the workflow and are not held to the prefixes.
        if target.depth > 0 and not _followed_host_allowed(target.host, options):
            raise VisitError("out_of_scope")
        try:
            result = await netmiko.send_commands(
                host=target.host,
                network_driver=None,
                platform=None,
                username=username,
                password=password,
                commands=[CDP_COMMAND],
                credential_reference=reference,
                use_textfsm=True,
                device_type=target.device_type,
                read_timeout=options.read_timeout,
                fail_on_cli_error=False,
                retry=options.retry,
            )
        except Exception as exc:
            failure = failure_from_exception(exc)
            raise VisitError(_visit_code(failure), failure) from exc
        finally:
            # Log out: this device is done, its socket must not stay open for the whole walk.
            await pool.close_host(target.host)
        if not result.success:
            raise VisitError(_visit_code(result.failure), result.failure)
        parsed = classify_cdp_output(result.command_outputs.get(CDP_COMMAND, result.output or ""))
        return Reading(parsed.neighbors, parsed.status.value)

    return visit


def _dry_run(
    seeds: dict[str, DeviceContext],
    context: WorkflowContext,
    node_id: str,
    options: DiscoverOptions,
) -> list[StepOutcome]:
    payload = {
        "would_visit_seeds": True,
        "commands": [CDP_COMMAND],
        "follow_neighbors": options.follow_neighbors,
        "permitted_prefixes": [str(p) for p in options.prefixes],
    }
    previewed = {
        device_id: with_discovery(
            record_dry_run(device, node_id=node_id, payload=payload), node_id, {"dry_run": True}
        )
        for device_id, device in seeds.items()
    }
    return [StepOutcome(name="success", context=context.model_copy(update={"devices": previewed}))]


def _build_outcomes(
    context: WorkflowContext,
    node_id: str,
    result: CrawlResult,
    seed_errors: dict[str, VisitError],
) -> list[StepOutcome]:
    seed_hosts = frozenset(v.target.host for v in result.visited if v.target.seed_id is not None)
    ok: dict[str, DeviceContext] = {}
    failed: dict[str, DeviceContext] = {}
    for visited in result.visited:
        target = visited.target
        if target.seed_id is None:
            device = discovered_device(visited, node_id)
            ok[device.id] = device
        elif visited.status != CdpStatus.OK.value:
            # Keep the record (cdp_status) on the failed device: it says why it failed.
            recorded = with_discovery(
                context.devices[target.seed_id], node_id, device_summary(visited)
            )
            code = _CDP_PROBLEM_CODES.get(visited.status, "cdp_no_output")
            failed[target.seed_id] = _fail(recorded, node_id, VisitError(code, _NO_CDP))
        else:
            ok[target.seed_id] = with_discovery(
                context.devices[target.seed_id], node_id, device_summary(visited)
            )
    for target, error in result.failed_seeds:
        if target.seed_id is not None:
            failed[target.seed_id] = _fail(context.devices[target.seed_id], node_id, error)
    for device_id, error in seed_errors.items():
        failed[device_id] = _fail(context.devices[device_id], node_id, error)

    for device_id, device in context.devices.items():
        if device_id not in ok and device_id not in failed:
            # The same device given twice: the crawler visits it once, under the first seed.
            ok[device_id] = with_discovery(device, node_id, {"skipped": "duplicate_seed"})

    summary: dict[str, Any] = step_summary(result, seed_hosts=seed_hosts)
    metadata = {**context.metadata, f"{node_id}.{RESULT_KEY}": summary}
    outcomes = [
        StepOutcome(
            name="success",
            context=context.model_copy(update={"devices": ok, "metadata": metadata}),
            summary=(
                f"visited {len(result.visited)} device(s), {len(result.seen)} seen but not visited"
            ),
        )
    ]
    if failed:
        outcomes.append(
            StepOutcome(
                name="failure",
                # The crawl record is on both exits: a failed seed's result must not be empty.
                context=context.model_copy(update={"devices": failed, "metadata": metadata}),
                summary=f"{len(failed)} seed device(s) failed",
            )
        )
    return outcomes


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service
    if not context.devices:
        return [StepOutcome(name="success", context=context)]

    options = parse_options(config)
    if options.follow_neighbors:
        ensure_following_allowed(enabled=settings.discover_network_follow_enabled)
    reference = resolve_config_reference(
        config,
        source_key="credential_source",
        param_key="credential_param",
        literal_key="credential_reference",
        run_inputs=run.run_inputs,
    )
    db = object_session(run)
    if db is None:
        raise RuntimeError("discover-network: WorkflowRun has no active DB session")
    username, password = resolve_ssh_credential(db, reference, acting_user_id=run.triggered_by_id)

    logger.info(
        "discover-network started run_id=%s seeds=%d follow=%s prefixes=%d max_devices=%d "
        "max_depth=%d dry_run=%s",
        run.id,
        len(context.devices),
        options.follow_neighbors,
        len(options.prefixes),
        options.max_devices,
        options.max_depth,
        options.dry_run,
    )
    if options.dry_run:
        return _dry_run(dict(context.devices), context, node_id, options)

    seeds: list[Target] = []
    seed_errors: dict[str, VisitError] = {}
    for device_id, device in context.devices.items():
        try:
            seeds.append(_seed_target(device_id, device, options))
        except VisitError as exc:
            seed_errors[device_id] = exc

    crawl_settings = CrawlSettings(
        follow=options.follow_neighbors,
        prefixes=options.prefixes,
        only_infrastructure=options.follow_only_infrastructure,
        max_devices=options.max_devices,
        max_depth=options.max_depth,
        concurrency=options.concurrency,
        override=options.network_driver_override,
        host_policy=check_discovered_host,
    )
    visit = _make_visit(
        netmiko=NetmikoService(pool=device_sessions),
        pool=device_sessions,
        credentials=(username, password, reference),
        options=options,
    )
    result = await crawl(seeds, visit, crawl_settings)
    outcomes = _build_outcomes(context, node_id, result, seed_errors)
    logger.info(
        "discover-network finished visited=%d seen=%d failed_seeds=%d limits=%s run_id=%s",
        len(result.visited),
        len(result.seen),
        len(result.failed_seeds) + len(seed_errors),
        ",".join(result.limits_hit) or "-",
        run.id,
    )
    return outcomes
