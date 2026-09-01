"""Executor for the compare-pyats-snapshot step.

Diffs one Genie feature between two already-captured pyats_snapshot artifacts
using genie.utils.diff.Diff, called through the pyATS shim's POST /v1/diff
(never imports pyats/genie directly -- see "Calling pyATS from a step" in
doc/WORKFLOW-STEPS.md).

The "live" side is resolved the same way store-artifact resolves
content_source="pyats_snapshot" (workflow_steps/common/content_resolver.py),
pointed at an upstream get-pyats-snapshot step via source_step_node_id. The
"reference" side is loaded the same way compare-data loads its reference --
via workflow_steps/compare_data/reference_reader.py, from git or the
filesystem. There is no cross-run artifact lookup anywhere in this codebase:
the reference file must be a JSON pyats_snapshot blob previously written by a
store-artifact step exporting an earlier get-pyats-snapshot run's content.

This step declares requires: [pyats_testbed] only to resolve which pyATS
source's shim credentials to use (via the bag's pyats_source_id) -- it never
reads the bag's password and never calls unwrap_secret()/seal_secret(), since
diffing two already-learned snapshots needs no device SSH credentials at all.

One step instance compares one or more Genie features (selected as a checkbox
group in the config panel, stored as ``features: list[str]``). Every selected
feature is read from the same per-device live and reference snapshot files --
there is no {feature} filename placeholder. A device routes to ``match`` only
when every selected feature is identical, to ``mismatch`` when any feature
differs, and to ``failure`` when any feature is absent/failed on either side or
the shim diff call itself fails. Per-feature diff text is stored under
``device.parsed["{node_id}.comparison_diff"]`` as a ``{feature: entry}`` map.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from sqlalchemy.orm import object_session

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
from services.pyats.common.exceptions import PyATSAPIError, PyATSValidationError
from services.pyats.credentials import PyATSCredentials
from services.pyats.source_config_service import (
    PyATSSourceConfigService,
    PyATSSourceNotFoundError,
)
from services.workflow_context.device_template import (
    TemplateRenderOptions,
    parse_strict_templates,
    render_device_template,
)
from workflow_steps.common.content_resolver import ExportableContent, list_exportable_content
from workflow_steps.common.pyats_features import parse_feature_list
from workflow_steps.compare_data.reference_reader import read_reference_text
from workflow_steps.compare_pyats_snapshot.config import get_config

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "compare-pyats-snapshot"
_OUTCOME_NAMES = ("match", "mismatch", "failure")


def _resolve_source_credentials(
    db: Session, source_ids: set[str]
) -> tuple[dict[str, PyATSCredentials], dict[str, str]]:
    """Resolve every distinct pyats_source_id once. Returns (credentials_by_id, error_by_id)."""
    config_service = PyATSSourceConfigService(db)
    credentials: dict[str, PyATSCredentials] = {}
    errors: dict[str, str] = {}
    for source_id in source_ids:
        try:
            credentials[source_id] = config_service.resolve_credentials(source_id)
        except (PyATSSourceNotFoundError, PyATSValidationError) as exc:
            errors[source_id] = str(exc)
    return credentials, errors


def _fail_device(
    *, device: DeviceContext, device_id: str, node_id: str, code: str, message: str
) -> tuple[str, DeviceContext, str, dict[str, Any] | None]:
    err = DeviceError(node_id=node_id, step_id=_STEP_ID, code=code, message=message)
    failed = device.model_copy(
        update={"status": DeviceStatus.FAILED, "errors": [*device.errors, err]}
    )
    return device_id, failed, "failure", None


def _extract_feature(
    snapshot: dict[str, Any], feature: str, *, side: str
) -> tuple[Any, str | None]:
    """Return (data, error_message); error_message is None on success."""
    entry = snapshot.get(feature)
    if not isinstance(entry, dict):
        return None, f"{side} snapshot has no data for feature {feature!r}"
    if not entry.get("success"):
        error = entry.get("error") or "unknown error"
        return None, f"{side} snapshot's {feature!r} feature failed: {error}"
    data = entry.get("data")
    if data is None:
        return None, f"{side} snapshot's {feature!r} feature has no data"
    return data, None


# (feature_name, "match" | "mismatch", diff_text when mismatch else None)
_FeatureResult = tuple[str, str, str | None]


async def _build_device_result(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    features: list[str],
    feature_results: list[_FeatureResult],
    reference_path: str,
    reference_location: str,
    context_run_id: str | None,
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, str, dict[str, Any] | None]:
    """Fold per-feature diff results into one device outcome.

    Routes to ``match`` only when every selected feature is identical; otherwise
    ``mismatch``, storing one diff artifact per differing feature.
    """
    comparison_diff_key = f"{node_id}.comparison_diff"
    diff_map: dict[str, dict[str, Any]] = {}
    per_feature: dict[str, dict[str, Any]] = {}
    mismatched_features: list[str] = []

    for feature, status, diff_text in feature_results:
        if status != "mismatch":
            per_feature[feature] = {"matched": True}
            continue
        mismatched_features.append(feature)
        text = diff_text or ""
        diff_ref = await artifact_service.store(
            content=text,
            kind="comparison_diff",
            device_id=device_id,
            run_id=context_run_id,
            media_type="text/plain",
        )
        # A format-agnostic stand-in for additions/deletions: Genie's str(Diff)
        # line prefixes are not confirmed against a real pyATS install (see
        # doc/PYATS_INTEGRATION.md "Open items"), so we don't try to parse them.
        diff_stats = {"line_count": sum(1 for line in text.splitlines() if line.strip())}
        diff_map[feature] = {
            "kind": "comparison_diff",
            "matched": False,
            "artifact_ref": diff_ref.model_dump(mode="json"),
            "diff_stats": diff_stats,
            "reference_location": reference_location,
            "reference_path": reference_path,
            "step_node_id": node_id,
            "output_key": "comparison_diff",
            "feature": feature,
        }
        per_feature[feature] = {"matched": False, "diff_stats": diff_stats}

    matched = not mismatched_features
    summary: dict[str, Any] = {
        "kind": "comparison_result",
        "matched": matched,
        "features": list(features),
        "mismatched_features": mismatched_features,
        "per_feature": per_feature,
        "reference_location": reference_location,
        "reference_path": reference_path,
        "step_node_id": node_id,
    }
    if not matched:
        summary["comparison_diff_key"] = comparison_diff_key

    parsed = dict(device.parsed)
    parsed[f"{node_id}.comparison"] = summary
    if diff_map:
        parsed[comparison_diff_key] = diff_map
    enriched = device.model_copy(
        update={
            "parsed": parsed,
            "capabilities": device.capabilities | {Capability.PARSED},
            "status": DeviceStatus.OK,
        }
    )
    record = {
        "device_id": device_id,
        "features": list(features),
        "reference_path": reference_path,
        "reference_location": reference_location,
        "matched": matched,
        "mismatched_features": mismatched_features,
    }
    return device_id, enriched, "match" if matched else "mismatch", record


def _resolve_live_export_item(
    device: DeviceContext,
    device_id: str,
    *,
    source_step_node_id: str,
    parsed_output_key: str | None,
) -> ExportableContent | None:
    export_items = list_exportable_content(
        device,
        content_source="pyats_snapshot",
        source_step_node_id=source_step_node_id,
        parsed_output_key=parsed_output_key,
    )
    if not export_items:
        return None
    item = export_items[0]
    if len(export_items) > 1:
        logger.warning(
            "%s device=%s has %d pyats_snapshot export items; using first only",
            _STEP_ID,
            device_id,
            len(export_items),
        )
    return item


async def _compare_one_device(
    *,
    device_id: str,
    device: DeviceContext,
    node_id: str,
    features: list[str],
    source_step_node_id: str,
    parsed_output_key: str | None,
    config: dict[str, Any],
    exclude_keys: list[str],
    context_run_id: str | None,
    source_credentials: dict[str, PyATSCredentials],
    source_errors: dict[str, str],
    artifact_service: ArtifactService,
) -> tuple[str, DeviceContext, str, dict[str, Any] | None]:
    bag = device.attribute_bags.get("pyats_testbed")
    if not isinstance(bag, dict):
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="missing_testbed",
            message="No pyats_testbed bag found -- add an Add Testbed step upstream",
        )

    source_id = str(bag.get("pyats_source_id") or "")
    if source_id in source_errors:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="source_error",
            message=source_errors[source_id],
        )
    shim_credentials = source_credentials.get(source_id)
    if shim_credentials is None:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="source_error",
            message=f"pyATS source {source_id!r} could not be resolved",
        )

    item = _resolve_live_export_item(
        device,
        device_id,
        source_step_node_id=source_step_node_id,
        parsed_output_key=parsed_output_key,
    )
    if item is None:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="missing_content",
            message=(
                "No pyats_snapshot content available for this device. "
                "Add an upstream Get Snapshot step."
            ),
        )

    try:
        live_text = await artifact_service.resolve(item.artifact_ref)
        live_snapshot = json.loads(live_text)
    except json.JSONDecodeError:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="invalid_snapshot",
            message="Live snapshot artifact is not valid JSON",
        )

    reference_path = render_device_template(
        str(config.get("filename_template") or "").strip(),
        device,
        extra=dict(item.extra),
        options=TemplateRenderOptions(
            strict=parse_strict_templates(config),
            run_id=context_run_id,
        ),
    )

    try:
        reference_text = await read_reference_text(config=config, relative_path=reference_path)
    except FileNotFoundError as exc:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="missing_reference",
            message=str(exc),
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator as a device failure
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="reference_error",
            message=str(exc),
        )

    try:
        reference_snapshot = json.loads(reference_text)
    except json.JSONDecodeError:
        return _fail_device(
            device=device,
            device_id=device_id,
            node_id=node_id,
            code="invalid_snapshot",
            message="Reference snapshot file is not valid JSON snapshot content",
        )

    reference_location = str(config.get("reference_location") or "filesystem").strip().lower()

    shim = service_factory.get_pyats_app_service()
    feature_results: list[_FeatureResult] = []
    for feature in features:
        live_data, live_error = _extract_feature(live_snapshot, feature, side="Live")
        if live_error is not None:
            return _fail_device(
                device=device,
                device_id=device_id,
                node_id=node_id,
                code="missing_feature",
                message=live_error,
            )

        reference_data, reference_error = _extract_feature(
            reference_snapshot, feature, side="Reference"
        )
        if reference_error is not None:
            return _fail_device(
                device=device,
                device_id=device_id,
                node_id=node_id,
                code="missing_feature",
                message=reference_error,
            )

        try:
            response = await shim.diff(
                shim_credentials,
                snapshot_a=live_data,
                snapshot_b=reference_data,
                exclude_keys=exclude_keys,
            )
        except (PyATSAPIError, PyATSValidationError) as exc:
            return _fail_device(
                device=device,
                device_id=device_id,
                node_id=node_id,
                code="shim_error",
                message=f"{feature}: {exc}",
            )

        if response.get("identical"):
            feature_results.append((feature, "match", None))
        else:
            feature_results.append((feature, "mismatch", str(response.get("diff") or "")))

    return await _build_device_result(
        device_id=device_id,
        device=device,
        node_id=node_id,
        features=features,
        feature_results=feature_results,
        reference_path=reference_path,
        reference_location=reference_location,
        context_run_id=context_run_id,
        artifact_service=artifact_service,
    )


async def execute(
    *,
    config: dict[str, Any],
    context: WorkflowContext,
    run: WorkflowRun,
    artifact_service: ArtifactService,
    node_id: str,
    device_sessions: DeviceSessionPool,
) -> list[StepOutcome]:
    del device_sessions  # unused: diff is pure computation via the shim, not Netmiko

    merged_config = {**get_config(), **config}

    features = parse_feature_list(merged_config.get("features"), step_id=_STEP_ID)
    source_step_node_id = str(merged_config.get("source_step_node_id") or "").strip()
    if not source_step_node_id:
        raise ValueError(f"{_STEP_ID}: source_step_node_id is required")
    filename_template = str(merged_config.get("filename_template") or "").strip()
    if not filename_template:
        raise ValueError(f"{_STEP_ID}: filename_template is required")
    parsed_output_key = str(merged_config.get("parsed_output_key") or "").strip() or None
    raw_exclude_keys = merged_config.get("exclude_keys")
    exclude_keys = (
        [str(key).strip() for key in raw_exclude_keys if str(key).strip()]
        if isinstance(raw_exclude_keys, list)
        else []
    )

    if not context.devices:
        return [StepOutcome(name=outcome_name, context=context) for outcome_name in _OUTCOME_NAMES]

    db = object_session(run)
    if db is None:
        raise RuntimeError(f"{_STEP_ID}: WorkflowRun has no active DB session")

    logger.info(
        "%s started run_id=%s node_id=%s devices=%d features=%s source_step_node_id=%s "
        "exclude_keys=%s",
        _STEP_ID,
        run.id,
        node_id,
        len(context.devices),
        features,
        source_step_node_id,
        exclude_keys,
    )

    source_ids = {
        str(device.attribute_bags["pyats_testbed"]["pyats_source_id"])
        for device in context.devices.values()
        if isinstance(device.attribute_bags.get("pyats_testbed"), dict)
        and device.attribute_bags["pyats_testbed"].get("pyats_source_id")
    }
    source_credentials, source_errors = _resolve_source_credentials(db, source_ids)

    results = await asyncio.gather(
        *[
            _compare_one_device(
                device_id=device_id,
                device=device,
                node_id=node_id,
                features=features,
                source_step_node_id=source_step_node_id,
                parsed_output_key=parsed_output_key,
                config=merged_config,
                exclude_keys=exclude_keys,
                context_run_id=context.run_id,
                source_credentials=source_credentials,
                source_errors=source_errors,
                artifact_service=artifact_service,
            )
            for device_id, device in context.devices.items()
        ]
    )

    buckets: dict[str, dict[str, DeviceContext]] = {"match": {}, "mismatch": {}, "failure": {}}
    comparison_records: list[dict[str, Any]] = []
    for device_id, updated_device, bucket_name, record in results:
        buckets[bucket_name][device_id] = updated_device
        if record is not None:
            comparison_records.append(record)

    counts = {name: len(buckets[name]) for name in _OUTCOME_NAMES}
    metadata = dict(context.metadata)
    metadata[f"{node_id}.comparison_counts"] = counts
    if comparison_records:
        metadata[f"{node_id}.comparisons"] = comparison_records

    logger.info("%s finished counts=%s run_id=%s", _STEP_ID, counts, run.id)

    return [
        StepOutcome(
            name=outcome_name,
            context=context.model_copy(
                update={"devices": dict(buckets[outcome_name]), "metadata": metadata}
            ),
        )
        for outcome_name in _OUTCOME_NAMES
    ]
