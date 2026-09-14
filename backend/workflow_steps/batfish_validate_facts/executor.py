"""Executor for the batfish-validate-facts step.

Wraps Batfish's ``validate_facts`` question -- checks expected configuration
facts (hostname, NTP/TACACS/DNS servers, interfaces, BGP/OSPF settings, etc.)
against what Batfish actually parsed from each device's config in an
already-initialized snapshot. See doc/BATFISH_INTEGRATION.md "Batfish
Validate Facts" for the full design and the gotchas below, confirmed by
reading the installed ``pybatfish`` source directly rather than assumed:

- ``Session.validate_facts(expected_facts, snapshot=None)`` takes a
  **directory path**, not YAML text -- it reads every file in that directory
  and merges their ``nodes:`` maps (``pybatfish.client._facts.load_facts``).
  We build that directory ourselves in a ``tempfile.TemporaryDirectory()``,
  same pattern as ``batfish-init-snapshot``'s config upload.
- Node-name lookup in the diff is a **plain dict key**, not a
  case-insensitive nodeSpec match like the other Batfish query steps use --
  Batfish canonicalizes hostnames to lowercase, so every node key we write is
  lowercased first, or a device with any uppercase in its name would
  silently never get checked.
- Batfish's own actual-facts encapsulation always stamps
  ``version: "batfish_v0"`` (``pybatfish.client._facts.BATFISH_FACT_VERSION``).
  If our expected-facts file carried any other literal version string (e.g.
  the "1.0" convention from Batfish's own public docs), *every* node would
  report as mismatched purely on the version field, masking real results.
  We drop any ``version`` key before writing, letting pybatfish's own
  ``load_facts()`` default it correctly.

Unlike a compare-pyats-snapshot-style per-feature diff, this step evaluates
one Batfish call for the whole device batch (calling validate_facts once per
device would be wasteful -- it internally re-fetches facts for every node in
the snapshot on every call, not just the ones being checked), then
partitions devices by the returned per-node result.
"""

from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

import service_factory
from core.models.runs import WorkflowRun
from models.workflow_context import (
    Capability,
    DeviceContext,
    DeviceError,
    DeviceStatus,
    StepOutcome,
    WorkflowContext,
)
from services.artifacts import ArtifactService
from workflow_steps.batfish_validate_facts.config import get_config
from workflow_steps.common.batfish_context import resolve_batfish_snapshot_ref
from workflow_steps.common.content_resolver import list_exportable_content
from workflow_steps.common.jinja_render import (
    JinjaTemplateError,
    build_jinja_context,
    render_jinja_template,
)

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "batfish-validate-facts"
_OUTCOME_NAMES = ("match", "mismatch", "failure")
_FACTS_SOURCES = frozenset({"rendered_yaml", "field"})


async def _resolve_rendered_yaml_fragment(
    *,
    device: DeviceContext,
    source_step_node_id: str,
    parsed_output_key: str | None,
    artifact_service: ArtifactService,
) -> tuple[dict[str, Any] | None, str | None]:
    """Returns (nodes_fragment, error_message) -- exactly one is non-None."""
    items = list_exportable_content(
        device,
        content_source="rendered_template",
        source_step_node_id=source_step_node_id,
        parsed_output_key=parsed_output_key,
    )
    if not items:
        return None, (
            "No rendered facts YAML found for this device -- add an upstream "
            "Render Jinja Template step producing the expected-facts content."
        )
    text = await artifact_service.resolve(items[0].artifact_ref)
    try:
        parsed_yaml = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, f"Rendered content is not valid YAML: {exc}"
    if not isinstance(parsed_yaml, dict) or not isinstance(parsed_yaml.get("nodes"), dict):
        return None, "Rendered YAML must have a top-level 'nodes' mapping"
    return parsed_yaml["nodes"], None


def _resolve_field_fragment(rendered_value: str, fact_key: str) -> dict[str, Any]:
    """Lets one Jinja-rendered text field represent a scalar or a
    YAML/JSON-parseable list, e.g. ``10.0.0.1`` or ``[10.0.0.1, 10.0.0.2]``."""
    try:
        parsed_value = yaml.safe_load(rendered_value)
    except yaml.YAMLError:
        parsed_value = rendered_value
    if parsed_value is None:
        parsed_value = rendered_value
    return {fact_key: parsed_value}


async def _prepare_contribution(
    *,
    device: DeviceContext,
    node_id: str,
    facts_source: str,
    merged_config: dict[str, Any],
    context: WorkflowContext,
    artifact_service: ArtifactService,
) -> tuple[str, dict[str, Any]] | DeviceError:
    """Resolve this device's one-node expected-facts fragment.

    Returns (node_name, fact_fields) on success -- node_name is always
    device.name lowercased, matching Batfish's own hostname canonicalization
    -- or a DeviceError describing why this device couldn't contribute.
    """
    node_name = device.name.strip().lower()
    if not node_name:
        return DeviceError(
            node_id=node_id,
            step_id=_STEP_ID,
            code="missing_name",
            message="Device has no name to use as a Batfish node key",
        )

    if facts_source == "field":
        fact_key = str(merged_config.get("fact_key") or "").strip()
        fact_template = str(merged_config.get("fact_value") or "")
        try:
            rendered_value = render_jinja_template(
                fact_template,
                build_jinja_context(
                    device, run_id=context.run_id, workflow_id=context.workflow_id
                ),
            )
        except JinjaTemplateError as exc:
            return DeviceError(
                node_id=node_id, step_id=_STEP_ID, code="render_error", message=str(exc)
            )
        return node_name, _resolve_field_fragment(rendered_value, fact_key)

    # facts_source == "rendered_yaml"
    source_step_node_id = str(merged_config.get("source_step_node_id") or "").strip()
    parsed_output_key = str(merged_config.get("parsed_output_key") or "").strip() or None
    nodes_fragment, error = await _resolve_rendered_yaml_fragment(
        device=device,
        source_step_node_id=source_step_node_id,
        parsed_output_key=parsed_output_key,
        artifact_service=artifact_service,
    )
    if error is not None or nodes_fragment is None:
        return DeviceError(
            node_id=node_id,
            step_id=_STEP_ID,
            code="missing_content",
            message=error or "No expected-facts content resolved",
        )
    lowered = {str(key).strip().lower(): value for key, value in nodes_fragment.items()}
    if node_name not in lowered:
        return DeviceError(
            node_id=node_id,
            step_id=_STEP_ID,
            code="node_key_mismatch",
            message=(
                f"Rendered facts YAML has no node key matching this device's name "
                f"({device.name!r}, case-insensitive); found: {sorted(nodes_fragment)}"
            ),
        )
    return node_name, lowered[node_name]


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del device_sessions  # unused: Batfish is reached via pybatfish, not Netmiko

    merged_config = {**get_config(), **config}
    facts_source = str(merged_config.get("facts_source") or "rendered_yaml").strip().lower()
    if facts_source not in _FACTS_SOURCES:
        raise ValueError(f"{_STEP_ID}: facts_source must be one of {sorted(_FACTS_SOURCES)}")
    if facts_source == "rendered_yaml":
        if not str(merged_config.get("source_step_node_id") or "").strip():
            raise ValueError(
                f"{_STEP_ID}: source_step_node_id is required when facts_source is 'rendered_yaml'"
            )
    elif not str(merged_config.get("fact_key") or "").strip():
        raise ValueError(f"{_STEP_ID}: fact_key is required when facts_source is 'field'")

    output_key = str(merged_config.get("output_key") or "batfish_validate_facts").strip() or (
        "batfish_validate_facts"
    )

    if not context.devices:
        return [StepOutcome(name=outcome_name, context=context) for outcome_name in _OUTCOME_NAMES]

    batfish = service_factory.get_batfish_app_service()
    snap = await resolve_batfish_snapshot_ref(
        context=context, config=merged_config, run=run, batfish=batfish
    )

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d facts_source=%s network=%s snapshot=%s",
        _STEP_ID,
        run.id,
        node_id,
        len(context.devices),
        facts_source,
        snap.network,
        snap.snapshot,
    )

    buckets: dict[str, dict[str, DeviceContext]] = {"match": {}, "mismatch": {}, "failure": {}}
    contributions: dict[str, str] = {}  # device_id -> node_name
    node_fragments: dict[str, dict[str, Any]] = {}  # node_name -> fact fields

    for device_id, device in context.devices.items():
        result = await _prepare_contribution(
            device=device,
            node_id=node_id,
            facts_source=facts_source,
            merged_config=merged_config,
            context=context,
            artifact_service=artifact_service,
        )
        if isinstance(result, DeviceError):
            failed = device.model_copy(
                update={"status": DeviceStatus.FAILED, "errors": [*device.errors, result]}
            )
            buckets["failure"][device_id] = failed
            continue
        node_name, fields = result
        contributions[device_id] = node_name
        node_fragments[node_name] = fields

    mismatches: dict[str, Any] = {}
    if node_fragments:
        with tempfile.TemporaryDirectory(prefix="batfish-facts-") as tmpdir:
            expected_dir = Path(tmpdir) / "expected"
            expected_dir.mkdir()
            # Deliberately no "version" key -- see module docstring's
            # version gotcha; pybatfish's own load_facts() defaults it.
            (expected_dir / "nodes.yaml").write_text(
                yaml.safe_dump({"nodes": node_fragments}, sort_keys=False),
                encoding="utf-8",
            )
            mismatches = await batfish.validate_facts(
                snap.connection,
                batfish_network=snap.network,
                expected_facts_dir=str(expected_dir),
                snapshot=snap.snapshot,
            )

    for device_id, node_name in contributions.items():
        device = context.devices[device_id]
        node_mismatch = mismatches.get(node_name)
        parsed = dict(device.parsed)
        parsed[f"{node_id}.{output_key}"] = {"parsed": node_mismatch or {}, "error": None}
        enriched = device.model_copy(
            update={
                "parsed": parsed,
                "capabilities": device.capabilities | {Capability.PARSED},
                "status": DeviceStatus.OK,
            }
        )
        if node_mismatch:
            buckets["mismatch"][device_id] = enriched
        else:
            buckets["match"][device_id] = enriched

    content = json.dumps(mismatches, indent=2, default=str)
    artifact_ref = await artifact_service.store(
        content=content,
        kind="batfish_result",
        device_id=f"batfish-{node_id}",
        run_id=context.run_id,
        media_type="application/json",
    )
    metadata = dict(context.metadata)
    metadata[f"{node_id}.{output_key}"] = {
        "kind": "batfish_result",
        "question": "validateFacts",
        "artifact_ref": artifact_ref.model_dump(mode="json"),
        "row_count": len(mismatches),
        "node_count": len(node_fragments),
    }

    counts = {name: len(buckets[name]) for name in _OUTCOME_NAMES}
    logger.info(
        "%s finished run_id=%s counts=%s mismatched_nodes=%d",
        _STEP_ID,
        run.id,
        counts,
        len(mismatches),
    )

    return [
        StepOutcome(
            name=outcome_name,
            context=context.model_copy(
                update={"devices": dict(buckets[outcome_name]), "metadata": metadata}
            ),
        )
        for outcome_name in _OUTCOME_NAMES
    ]
