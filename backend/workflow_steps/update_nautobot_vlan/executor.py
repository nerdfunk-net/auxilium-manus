"""Executor for the update-nautobot-vlan step.

All Nautobot work is done by the shared ``DeviceCommonService`` (VLANManager): the step resolves
the VLAN (by UUID, or by VID and optional VLAN group) and the new values per device, looks up
status, role, VLAN group and locations once per distinct value, and reports per device. An empty
field is left unchanged; the locations are replaced, extended or reduced depending on the mode.
The pipeline is ``common/nautobot_object_update.py`` (shared with Update IP Prefix); this module
holds the config, the VLAN-specific selection and the "VLANs from interfaces" mode.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.nautobot.devices.common import DeviceCommonService
from services.nautobot.managers.vlan_manager import (
    LOCATIONS_MODES,
    LocationsMode,
    VlanPartialUpdateError,
)
from workflow_steps.common.location_list import split_locations
from workflow_steps.common.nautobot_object_update import (
    ObjectUpdateRequest,
    ObjectUpdateSpec,
    empty_outcomes,
    run_object_update,
)
from workflow_steps.common.nautobot_step import bind_nautobot_client
from workflow_steps.common.step_flags import parse_bool_flag
from workflow_steps.update_nautobot_vlan.interfaces_mode import run_from_interfaces

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "update-nautobot-vlan"
_FIELDS = ("name", "description", "status", "role", "locations")
_VID_RANGE = range(1, 4095)


def _normalize_vid(text: str) -> str | None:
    # ASCII digits only: str.isdigit() accepts "\u00b2", which int() then refuses.
    if not re.fullmatch(r"[0-9]+", text) or int(text) not in _VID_RANGE:
        return None
    return str(int(text))


async def _find_vlans(common: DeviceCommonService, key: str, group_id: str | None) -> list[str]:
    return await common.find_vlans(int(key), group_id)


async def _update_vlan(
    common: DeviceCommonService, vlan_id: str, fields: Mapping[str, str], **kwargs: Any
) -> bool:
    return await common.update_vlan(vlan_id, fields, **kwargs)


_SPEC = ObjectUpdateSpec(
    step_id=_STEP_ID,
    noun="VLAN",
    plural="VLANs",
    code_stem="vlan",
    content_type="ipam.vlan",
    counts_key="update_vlan_counts",
    id_field="vlan_id",
    key_field="vid",
    scope_field="vlan_group",
    scope_label="VLAN group",
    scope_ignored_with_id=False,
    normalize_key=_normalize_vid,
    key_invalid_message="vid must be a number from 1 to 4094",
    no_match_message="No VLAN with this VID was found in Nautobot",
    several_match_message="More than one VLAN has this VID; set vlan_group or use vlan_id",
    resolve_scope=lambda common, name: common.resolve_vlan_group_id(name),
    find=_find_vlans,
    update=_update_vlan,
    partial_error=VlanPartialUpdateError,
)


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    vlan_id_expression: str
    vid_expression: str
    vlan_group_expression: str
    expressions: dict[str, str]
    location_expressions: tuple[str, ...]
    locations_mode: LocationsMode
    from_interfaces: bool = False
    dry_run: bool = False


# Keys the "VLANs from interfaces" mode does not take: it only adds the device's own location.
_INTERFACE_MODE_REFUSED = ("vlan_id", "vid", "vlan_group", *_FIELDS)


@dataclass(frozen=True)
class _Bound:
    common: DeviceCommonService


def _text(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if isinstance(value, list):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return str(value or "").strip()


def _parse_config(config: dict[str, Any]) -> _ParsedConfig:
    source_id = _text(config, "nautobot_source_id")
    if not source_id:
        raise ValueError(f"{_STEP_ID}: nautobot_source_id is not configured")
    dry_run = parse_bool_flag(config, "dry_run")
    if parse_bool_flag(config, "vlans_from_interfaces"):
        extra = [key for key in _INTERFACE_MODE_REFUSED if _text(config, key)]
        if extra:
            raise ValueError(
                f"{_STEP_ID}: vlans_from_interfaces only adds the device's location; "
                f"clear {', '.join(extra)}"
            )
        return _ParsedConfig(
            source_id=source_id,
            vlan_id_expression="",
            vid_expression="",
            vlan_group_expression="",
            expressions={},
            location_expressions=(),
            locations_mode="add",
            from_interfaces=True,
            dry_run=dry_run,
        )
    if dry_run:
        # Only the interfaces mode previews; ignoring the flag here would write to Nautobot.
        raise ValueError(
            f"{_STEP_ID}: dry_run only works with vlans_from_interfaces; "
            "switch it off or the step would write"
        )
    vlan_id = _text(config, "vlan_id")
    vid = _text(config, "vid")
    if not vlan_id and not vid:
        raise ValueError(f"{_STEP_ID}: configure vlan_id or vid to select the VLAN")
    expressions = {field: _text(config, field) for field in _FIELDS if field != "locations"}
    locations = tuple(split_locations(_text(config, "locations")))
    if not any(expressions.values()) and not locations:
        raise ValueError(
            f"{_STEP_ID}: configure at least one field to update ({', '.join(_FIELDS)})"
        )
    mode = _text(config, "locations_mode") or "replace"
    if mode not in LOCATIONS_MODES:
        raise ValueError(f"{_STEP_ID}: locations_mode must be one of {', '.join(LOCATIONS_MODES)}")
    return _ParsedConfig(
        source_id=source_id,
        vlan_id_expression=vlan_id,
        vid_expression=vid,
        vlan_group_expression=_text(config, "vlan_group"),
        expressions=expressions,
        location_expressions=locations,
        locations_mode=mode,  # type: ignore[arg-type]  # checked against LOCATIONS_MODES above
    )


def _bind_nautobot(run: WorkflowRun, source_id: str) -> _Bound:
    client = bind_nautobot_client(run, source_id, step_id=_STEP_ID)
    return _Bound(DeviceCommonService(client))


def _request(parsed: _ParsedConfig) -> ObjectUpdateRequest:
    return ObjectUpdateRequest(
        id_expression=parsed.vlan_id_expression,
        key_expression=parsed.vid_expression,
        scope_expression=parsed.vlan_group_expression,
        expressions=parsed.expressions,
        location_expressions=parsed.location_expressions,
        locations_mode=parsed.locations_mode,
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
    del artifact_service, device_sessions

    parsed = _parse_config(config)
    if not context.devices:
        return empty_outcomes(_SPEC, context, node_id)

    bound = _bind_nautobot(run, parsed.source_id)
    if parsed.from_interfaces:
        return await run_from_interfaces(
            common=bound.common, context=context, node_id=node_id, dry_run=parsed.dry_run
        )
    request = _request(parsed)
    return await run_object_update(
        _SPEC, request, common=bound.common, context=context, node_id=node_id
    )
