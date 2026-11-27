"""Executor for the add-to-ise step.

Creates a new ``NetworkDevice`` entry in Cisco ISE for each device in the
workflow context, with an IPv4 address, an optional set of network device
group memberships, and a TACACS+ shared secret. ``device_name``,
``description``, ``ip_address``, ``new_key`` and each ``device_groups`` entry
accept either a fixed value or a ``{path.to.value}`` expression resolved per
device against the device's attribute bags (see
``workflow_steps.common.value_expression``), the same convention
``update-ise-tacacs-key`` uses for ``new_key``.

A ``device_groups`` expression must resolve to an *existing* attribute: a
missing/null one fails the device (``device_group_unresolved``), while one that
exists but is blank adds no group for that entry.

``create_missing_groups`` (default off): when enabled, every resolved
``device_groups`` entry that does not yet exist in ISE is created (with any
missing ancestors, see ``group_ensure``) before the device is created; a group
that cannot be created fails the device (``ise_device_group_create_failed``).
When off, ISE's own "NDG cannot be found" rejection fails the device.

Outcomes: devices are routed per outcome handle.

* ``"success"`` — devices that were created.
* ``"exists"`` — devices ISE refused to create because a network device with
  that name already exists. They are passed through unchanged (not failed).
* ``"failure"`` — devices that could not be created, each marked
  ``DeviceStatus.FAILED`` with a ``DeviceError``: an unresolved expression, or
  ISE rejecting the create for any reason other than a duplicate name. It also
  carries the whole input context when the step itself broke: ISE couldn't be
  reached or authentication failed (a pre-flight ``test_connection()`` check,
  and any bare ``ISEAPIError`` raised mid-run), which affects every device
  equally.

Debugging: every device for which a create request was actually sent gets a
``RequestRecord`` in ``DeviceContext.requests[node_id]`` — the exact
``NetworkDevice`` body posted to ISE (after ``{path}`` resolution) and ISE's
response (or the error ISE returned). It is recorded for created,
already-existing and rejected devices alike, with the TACACS+ shared secret
redacted, and is shown in the run's device detail view only — it is not an
attribute bag, so other steps and ``{path}`` expressions never see it.
Devices that failed before a request was built (unresolved expressions) have
none.

``single_connect_mode`` sets ISE's ``tacacsSettings.connectModeOptions`` (the
"Enable Single Connect Mode" checkbox): ``OFF`` (default, unchecked),
``ON_LEGACY`` (Legacy Cisco Device) or ``ON_DRAFT_COMPLIANT`` (TACACS Draft
Compliance Single Connect Support). It is a fixed choice, not a ``{path}``
expression; any other value raises ``ValueError``.

``ip_address`` may resolve to a CIDR-suffixed value (e.g. ``10.0.0.1/24``,
the format Nautobot's ``primary_ip4`` is commonly stored/templated in) —
ISE's ``NetworkDeviceIPList.ipaddress`` field rejects a CIDR suffix outright
with a ``400 Illegal IP Address`` error. The resolved value is therefore split
into the bare host address (``ipaddress``) and a separate ``mask``. The mask
is, in order of precedence: the optional ``netmask_override`` config value
(e.g. ``32`` or ``/32``), the suffix of the resolved ``ip_address`` **only when
``use_address_prefix`` is enabled**, else ``/32`` (a single host entry, matching
``tools/ise/ise_test.py``). The prefix is not used by default because Nautobot's
``primary_ip4`` carries the interface prefix and an ISE entry with e.g. ``/24``
covers the whole subnet.

When the default ``{primary_ip4}`` expression is used, ``device.primary_ip4``
is only populated by inventory steps that fetch full device records (Get from
Nautobot, Get from Git). A device sourced via Get from List/Get from ISE and
enriched only by Get Nautobot Attributes never gets that scalar field set —
the IP lives nested at ``nautobot.primary_ip4.address`` instead. ``{primary_ip4}``
falls back to that nested path automatically, as
``common/primary_ip.py::effective_primary_ip4`` does for ``get-ise-tacacs-key``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import service_factory
from core.models.runs import WorkflowRun
from models.failure import FailureInfo
from models.workflow_context import (
    DeviceContext,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from services.ise.common.exceptions import ALREADY_EXISTS_CODE, ISEAPIError, ISEValidationError
from workflow_steps.add_to_ise.fields import (
    resolve_device_fields,
)
from workflow_steps.add_to_ise.group_ensure import DeviceGroupEnsurer
from workflow_steps.add_to_ise.parse import (
    STEP_ID,
    ParsedConfig,
    parse_config,
)
from workflow_steps.add_to_ise.payload import (
    build_create_payload,
    enrich_device_after_create,
    with_request_record,
)
from workflow_steps.common.device_outcomes import outcomes_from_buckets
from workflow_steps.common.device_runner import AbortRun, Fail, run_per_device
from workflow_steps.common.failure_records import INVALID_INPUT
from workflow_steps.common.ise_step import build_ise_device_service, ise_credentials, preflight_ise
from workflow_steps.common.partial_outcomes import abort_outcomes

if TYPE_CHECKING:
    from services.ise.network_device_service import ISENetworkDeviceService
    from services.network.netmiko.session_pool import DeviceSessionPool


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _CreateOneResult:
    kind: Literal["created", "exists", "failed", "abort"]
    device: DeviceContext | None = None
    fail: Fail | None = None
    abort_message: str | None = None
    abort_failure: FailureInfo | None = None


def refusal(
    device: DeviceContext,
    *,
    code: str,
    message: str,
    failure: FailureInfo | None = None,
    carry: DeviceContext | None = None,
) -> Fail:
    """A device-level failure; ``carry`` is the device with what was learned before it failed."""
    logger.warning("%s: device '%s' failed (%s): %s", STEP_ID, device.name, code, message)
    return Fail(code, message, failure, device=carry)


def _build_group_ensurer(run: WorkflowRun, source_id: str) -> DeviceGroupEnsurer:
    group_service = service_factory.build_ise_network_device_group_service(
        ise_credentials(run, source_id, step_id=STEP_ID)
    )
    return DeviceGroupEnsurer(group_service)


async def _create_one_device(
    *,
    device: DeviceContext,
    cfg: ParsedConfig,
    device_service: ISENetworkDeviceService,
    source_id: str,
    node_id: str,
    context: WorkflowContext,
    group_ensurer: DeviceGroupEnsurer | None = None,
) -> _CreateOneResult:
    resolved = resolve_device_fields(device, cfg, context.run_id)
    if isinstance(resolved, tuple):
        failure_code, failure_message = resolved
        return _CreateOneResult(
            kind="failed",
            fail=refusal(
                device, code=failure_code, message=failure_message, failure=INVALID_INPUT
            ),
        )

    device_payload = build_create_payload(resolved)

    try:
        if group_ensurer is not None:
            for group_name in resolved.device_groups:
                await group_ensurer.ensure(group_name)
    except ISEValidationError as exc:
        return _CreateOneResult(
            kind="failed",
            fail=refusal(
                device,
                code="ise_device_group_create_failed",
                message=f"could not create missing device group for '{resolved.name}': {exc}",
                failure=exc.failure,
            ),
        )
    except ISEAPIError as exc:
        return _CreateOneResult(
            kind="abort",
            abort_message=f"lost connection to ISE source '{source_id}': {exc}",
            abort_failure=exc.failure,
        )

    try:
        created = await device_service.create_device(device_payload)
    except ISEValidationError as exc:
        if exc.code == ALREADY_EXISTS_CODE:
            logger.info(
                "%s: device '%s' already exists in ISE source '%s': %s",
                STEP_ID,
                resolved.name,
                source_id,
                exc,
            )
            exists_device = with_request_record(
                device,
                node_id=node_id,
                device_payload=device_payload,
                resolved_key=resolved.key,
                response={"error": str(exc)},
                ok=False,
            )
            return _CreateOneResult(kind="exists", device=exists_device)
        return _CreateOneResult(
            kind="failed",
            fail=refusal(
                device,
                code="ise_device_create_rejected",
                message=f"ISE rejected creating device '{resolved.name}': {exc}",
                failure=exc.failure,
                carry=with_request_record(
                    device,
                    node_id=node_id,
                    device_payload=device_payload,
                    resolved_key=resolved.key,
                    response={"error": str(exc)},
                    ok=False,
                ),
            ),
        )
    except ISEAPIError as exc:
        logger.warning(
            "%s: lost connection to ISE source '%s' while creating device '%s': %s",
            STEP_ID,
            source_id,
            resolved.name,
            exc,
        )
        return _CreateOneResult(
            kind="abort",
            abort_message=f"lost connection to ISE source '{source_id}': {exc}",
            abort_failure=exc.failure,
        )

    updated = enrich_device_after_create(device, device_payload, created, resolved.key, node_id)
    logger.info("%s: created device=%s ise_id=%s", STEP_ID, resolved.name, created.get("id"))
    return _CreateOneResult(kind="created", device=updated)


def _report(
    *, context: WorkflowContext, node_id: str, buckets: dict[str, dict[str, DeviceContext]]
) -> tuple[dict[str, Any], dict[str, str]]:
    """Log the totals; the count metadata and the summary of each handle."""
    created_count = len(buckets["success"])
    exists_count = len(buckets["exists"])
    failed_count = len(buckets["failure"])
    metadata = {
        f"{node_id}.total": len(context.devices),
        f"{node_id}.created_count": created_count,
        f"{node_id}.exists_count": exists_count,
        f"{node_id}.failed_count": failed_count,
    }

    if failed_count:
        logger.warning(
            "%s: %d/%d device(s) failed for node_id=%s — see the per-device warnings above "
            "for the reason each one failed",
            STEP_ID,
            failed_count,
            len(context.devices),
            node_id,
        )

    logger.info(
        "%s finished node_id=%s created=%d exists=%d failed=%d run_id=%s",
        STEP_ID,
        node_id,
        created_count,
        exists_count,
        failed_count,
        context.run_id,
    )

    summaries = {
        "success": f"created {created_count}",
        "exists": f"already exists {exists_count}",
        "failure": f"failed {failed_count}",
    }
    return metadata, summaries


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del artifact_service  # unused for this step

    parsed = parse_config(config)

    if not context.devices:
        return [
            StepOutcome(name="success", context=context),
            StepOutcome(name="exists", context=context),
            StepOutcome(name="failure", context=context),
        ]

    device_service = build_ise_device_service(run, parsed.source_id, step_id=STEP_ID)

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d",
        STEP_ID,
        context.run_id,
        node_id,
        len(context.devices),
    )

    unreachable = await preflight_ise(device_service, context, parsed.source_id, step_id=STEP_ID)
    if unreachable is not None:
        return unreachable

    group_ensurer = (
        _build_group_ensurer(run, parsed.source_id) if parsed.create_missing_groups else None
    )

    exists_ids: set[str] = set()

    async def work(device_id: str, device: DeviceContext) -> DeviceContext | Fail:
        result = await _create_one_device(
            device=device,
            cfg=parsed,
            device_service=device_service,
            source_id=parsed.source_id,
            node_id=node_id,
            context=context,
            group_ensurer=group_ensurer,
        )
        if result.kind == "abort":
            assert result.abort_message is not None  # noqa: S101  # type narrowing on result.kind
            raise AbortRun(result.abort_message, result.abort_failure)
        if result.kind == "failed":
            assert result.fail is not None  # noqa: S101  # type narrowing on result.kind
            return result.fail
        assert result.device is not None  # noqa: S101  # type narrowing on result.kind
        if result.kind == "exists":
            exists_ids.add(device_id)
        return result.device

    # One device after the other: a lost ISE connection stops the run (AbortRun) and the devices
    # already done keep their result.
    batch = await run_per_device(
        context, work, node_id=node_id, step_id=STEP_ID, concurrency=1
    )
    success_devices = {i: d for i, d in batch.ok.items() if i not in exists_ids}
    exists_devices = {i: d for i, d in batch.ok.items() if i in exists_ids}
    if batch.aborted is not None:
        return abort_outcomes(
            context=context,
            node_id=node_id,
            step_id=STEP_ID,
            done_ok=success_devices,
            done_failed=batch.failed,
            message=batch.aborted.message,
            failure=batch.aborted.failure,
            extra={"exists": exists_devices},
        )

    buckets = {"success": success_devices, "exists": exists_devices, "failure": batch.failed}
    metadata, summaries = _report(context=context, node_id=node_id, buckets=buckets)
    return outcomes_from_buckets(context, buckets, metadata=metadata, summaries=summaries)

