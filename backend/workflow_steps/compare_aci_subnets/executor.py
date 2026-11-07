"""Executor for the compare-aci-subnets step: ACI gateway subnets against Nautobot prefixes.

Report only: nothing is written to ACI or Nautobot. The full report is stored as a JSON artifact;
the run metadata carries the counts and the first few differences. The ``success`` outcome is
always emitted; ``differences`` as well when the two sources disagree, so a workflow can branch on
drift.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.aci.common.exceptions import AciAPIError, AciAuthError, AciValidationError
from services.artifacts import ArtifactService
from services.nautobot.common.exceptions import NautobotError
from workflow_steps.common.aci_targets import resolve_source_credentials
from workflow_steps.common.fact_entries import parse_output_key_config
from workflow_steps.common.nautobot_source import resolve_nautobot_credentials
from workflow_steps.common.step_flags import parse_bool_flag
from workflow_steps.compare_aci_subnets.compare import compare_subnets, parse_scope_prefixes

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

STEP_ID = "compare-aci-subnets"
DEFAULT_NAMESPACE = "Global"
DEFAULT_OUTPUT_KEY = "aci_subnet_report"
ARTIFACT_KIND = "aci_subnet_report"
# Differences copied into the run metadata (the artifact holds all of them).
METADATA_SAMPLE = 50


def _required(config: dict[str, Any], key: str) -> str:
    value = str(config.get(key) or "").strip()
    if not value:
        raise ValueError(f"{STEP_ID}: {key} is not configured")
    return value


def _scope_prefixes(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        raise ValueError(f"{STEP_ID}: scope_prefixes must be a list of prefixes")
    try:
        return [str(network) for network in parse_scope_prefixes([i for i in raw if i.strip()])]
    except ValueError as exc:
        raise ValueError(f"{STEP_ID}: {exc}") from exc


def _sample(items: list[dict[str, Any]] | None) -> list[str] | None:
    if items is None:
        return None
    return [item["prefix"] for item in items[:METADATA_SAMPLE]]


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del device_sessions  # no device is contacted

    aci_source = _required(config, "aci_source_id")
    nautobot_source = _required(config, "nautobot_source_id")
    namespace = _required({"namespace": config.get("namespace", DEFAULT_NAMESPACE)}, "namespace")
    namespace_from_vrf = parse_bool_flag(config, "namespace_from_vrf", default=False)
    scope = _scope_prefixes(config.get("scope_prefixes"))
    output_key = parse_output_key_config(
        config.get("output_key"), step_id=STEP_ID, default=DEFAULT_OUTPUT_KEY
    )

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{STEP_ID}: WorkflowRun has no active DB session")
    aci_credentials = resolve_source_credentials(db, [aci_source], step_id=STEP_ID)[aci_source]
    nautobot_credentials = resolve_nautobot_credentials(db, nautobot_source, step_id=STEP_ID)

    logger.info("%s started run_id=%s node_id=%s", STEP_ID, context.run_id, node_id)
    subnets = service_factory.build_aci_subnet_service(aci_credentials)
    prefixes = service_factory.build_nautobot_prefix_reader(nautobot_credentials)
    try:
        aci_subnets, nautobot_prefixes = await asyncio.gather(
            subnets.list_subnets(), prefixes.list_prefixes()
        )
    except AciValidationError as exc:
        raise ValueError(f"{STEP_ID}: {exc}") from exc
    except (AciAPIError, AciAuthError) as exc:
        # ``from exc`` keeps the cause chain: the runner reads the structured failure from it.
        raise RuntimeError(f"{STEP_ID}: APIC request failed: {exc}") from exc
    except NautobotError as exc:
        raise RuntimeError(f"{STEP_ID}: Nautobot request failed: {exc}") from exc

    report = compare_subnets(
        aci_subnets,
        nautobot_prefixes,
        namespace=namespace,
        namespace_from_vrf=namespace_from_vrf,
        scope_prefixes=scope,
    )
    artifact_ref = await artifact_service.store(
        content=json.dumps(report, indent=2, default=str),
        kind=ARTIFACT_KIND,
        device_id=f"aci-subnets-{node_id}",
        run_id=context.run_id,
        media_type="application/json",
    )
    summary = report["summary"]
    metadata = {
        **context.metadata,
        f"{node_id}.{output_key}": {
            "kind": ARTIFACT_KIND,
            "artifact_ref": artifact_ref.model_dump(mode="json"),
            "summary": summary,
            "missing_in_nautobot": _sample(report["missing_in_nautobot"]),
            "missing_in_aci": _sample(report["missing_in_aci"]),
            "overlaps": _sample(report["overlaps"]),
        },
    }
    logger.info(
        "%s finished run_id=%s aci=%d matched=%d missing_in_nautobot=%d",
        STEP_ID,
        context.run_id,
        summary["aci_subnets"],
        summary["matched"],
        summary["missing_in_nautobot"],
    )
    new_context = context.model_copy(update={"metadata": metadata})
    text = (
        f"{summary['matched']} matched, {summary['missing_in_nautobot']} missing in Nautobot, "
        f"{summary['overlaps']} overlap(s)"
    )
    outcomes = [StepOutcome(name="success", context=new_context, summary=text)]
    if summary["differences"]:
        outcomes.append(StepOutcome(name="differences", context=new_context, summary=text))
    return outcomes
