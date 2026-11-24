"""Executor for the update-nautobot-prefix step.

Changes an existing IP prefix in Nautobot through the shared ``DeviceCommonService``
(``PrefixManager.update_prefix``): the prefix is selected by UUID or by network and namespace, the
new values are resolved per device, status, role, namespace and location names are looked up once
per distinct value, and every device is reported. An empty field is left unchanged; the locations
are replaced, extended or reduced depending on the mode. ``prefixes_from_interfaces`` instead adds
each device's own location to the parent prefixes of its interface addresses
(``interfaces_mode.py``).
The pipeline is ``common/nautobot_object_update.py`` (shared with Update VLAN); this module holds
the config, the prefix-specific selection and the "prefixes from interfaces" mode.
"""

from __future__ import annotations

import ipaddress
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.models.runs import WorkflowRun
from models.workflow_context import StepOutcome, WorkflowContext
from services.artifacts import ArtifactService
from services.nautobot.devices.common import DeviceCommonService
from services.nautobot.managers.location_assignments import (
    LOCATIONS_MODES,
    LocationsMode,
    PartialUpdateError,
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
from workflow_steps.update_nautobot_prefix.interfaces_mode import run_from_interfaces

if TYPE_CHECKING:
    from services.network.netmiko.session_pool import DeviceSessionPool

logger = logging.getLogger(__name__)

_STEP_ID = "update-nautobot-prefix"
_FIELDS = ("description", "status", "role", "locations")
_VALUE_FIELDS = ("description", "status", "role")
# Keys the "prefixes from interfaces" mode does not take: it only adds the device's own location.
_INTERFACE_MODE_REFUSED = ("prefix_id", "prefix", "namespace", *_FIELDS)


def _normalize_network(text: str) -> str | None:
    try:
        # The canonical text is what Nautobot stores and what the lookup cache is keyed by.
        return str(ipaddress.ip_network(text, strict=True))
    except ValueError:
        return None


async def _find_prefixes(
    common: DeviceCommonService, key: str, namespace_id: str | None
) -> list[str]:
    return await common.find_prefixes(key, namespace_id)


async def _update_prefix(
    common: DeviceCommonService, prefix_id: str, fields: Mapping[str, str], **kwargs: Any
) -> bool:
    return await common.update_prefix(prefix_id, fields, **kwargs)


_SPEC = ObjectUpdateSpec(
    step_id=_STEP_ID,
    noun="prefix",
    plural="prefixes",
    code_stem="prefix",
    content_type="ipam.prefix",
    counts_key="update_prefix_counts",
    id_field="prefix_id",
    key_field="prefix",
    scope_field="namespace",
    scope_label="namespace",
    scope_ignored_with_id=True,
    normalize_key=_normalize_network,
    key_invalid_message="prefix is not a network address like 10.0.0.0/24",
    no_match_message="No prefix with this network was found in Nautobot",
    several_match_message=(
        "The prefix exists in more than one namespace; set namespace or use prefix_id"
    ),
    resolve_scope=lambda common, name: common.resolve_namespace_id(name),
    find=_find_prefixes,
    update=_update_prefix,
    partial_error=PartialUpdateError,
)


@dataclass(frozen=True)
class _ParsedConfig:
    source_id: str
    prefix_id_expression: str
    prefix_expression: str
    namespace_expression: str
    expressions: dict[str, str]
    location_expressions: tuple[str, ...]
    locations_mode: LocationsMode
    from_interfaces: bool = False
    dry_run: bool = False


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
    if parse_bool_flag(config, "prefixes_from_interfaces"):
        extra = [key for key in _INTERFACE_MODE_REFUSED if _text(config, key)]
        if extra:
            raise ValueError(
                f"{_STEP_ID}: prefixes_from_interfaces only adds the device's location; "
                f"clear {', '.join(extra)}"
            )
        return _ParsedConfig(
            source_id=source_id,
            prefix_id_expression="",
            prefix_expression="",
            namespace_expression="",
            expressions={},
            location_expressions=(),
            locations_mode="add",
            from_interfaces=True,
            dry_run=dry_run,
        )
    if dry_run:
        # Only the interfaces mode previews; ignoring the flag here would write to Nautobot.
        raise ValueError(
            f"{_STEP_ID}: dry_run only works with prefixes_from_interfaces; "
            "switch it off or the step would write"
        )
    prefix_id = _text(config, "prefix_id")
    prefix = _text(config, "prefix")
    if not prefix_id and not prefix:
        raise ValueError(f"{_STEP_ID}: configure prefix_id or prefix to select the prefix")
    expressions = {field: _text(config, field) for field in _VALUE_FIELDS}
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
        prefix_id_expression=prefix_id,
        prefix_expression=prefix,
        namespace_expression=_text(config, "namespace"),
        expressions=expressions,
        location_expressions=locations,
        locations_mode=mode,  # type: ignore[arg-type]  # checked against LOCATIONS_MODES above
    )


def _bind_nautobot(run: WorkflowRun, source_id: str) -> _Bound:
    client = bind_nautobot_client(run, source_id, step_id=_STEP_ID)
    return _Bound(DeviceCommonService(client))


def _request(parsed: _ParsedConfig) -> ObjectUpdateRequest:
    return ObjectUpdateRequest(
        id_expression=parsed.prefix_id_expression,
        key_expression=parsed.prefix_expression,
        scope_expression=parsed.namespace_expression,
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
