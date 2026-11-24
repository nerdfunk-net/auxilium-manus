"""Helpers shared by both modes of update-nautobot-ip (manual and "from interfaces").

Name -> id lookups (namespace, role, status; each distinct name asked of Nautobot once), the
resolution of ``{path}`` values, the namespace move (``parent_finder``) and the mapping of a failed
write to a device error.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from models.failure import FailureInfo
from models.workflow_context import DeviceContext, DeviceError
from services.nautobot.common.exceptions import NautobotNotFoundError
from services.nautobot.credentials_bound_client import CredentialsBoundNautobotClient
from services.nautobot.devices.common import DeviceCommonService
from workflow_steps.common.nautobot_plan_fields import (
    PlanError,
    bad_request_failure,
    not_found_failure,
)
from workflow_steps.common.nautobot_plan_fields import failed as shared_failed
from workflow_steps.common.nautobot_prefix_lookup import LookupFailure, find_containing_prefix
from workflow_steps.common.partial_outcomes import (
    NAUTOBOT_TEXT,
    device_error_from_exception,
    fail_device_with_error,
)

STEP_ID = "update-nautobot-ip"
IP_CONTENT_TYPE = "ipam.ipaddress"
# Order of the fields in the request and in the first-failure message.
FIELDS = ("namespace", "type", "role", "status", "dns_name", "description")
IP_TYPES = ("host", "dhcp", "slaac")

def failed(
    device: DeviceContext, *, node_id: str, code: str, message: str, failure: FailureInfo
) -> DeviceContext:
    return shared_failed(
        STEP_ID, device, node_id=node_id, code=code, message=message, failure=failure
    )


@dataclass(frozen=True)
class Plan:
    """One device's resolved values.

    ``values`` holds the fields sent as they are; the namespace is separate because Nautobot
    ignores it on an existing address: the step moves the address to a prefix of that namespace.
    """

    device: DeviceContext
    ip_id: str
    values: dict[str, str]
    namespace: str | None = None


@dataclass(frozen=True)
class SplitValues:
    """Resolved fields with the namespace apart (it is a move of the parent, not a field)."""

    values: dict[str, str]
    namespace: str | None


def split_values(resolved: dict[str, str], *, allow_empty: bool = False) -> SplitValues | PlanError:
    """The values to send and the namespace: empty values dropped, ``type`` validated."""
    values = {field: value for field, value in resolved.items() if value}
    namespace = values.pop("namespace", None)
    if "type" in values:
        ip_type = values["type"].lower()
        if ip_type not in IP_TYPES:
            return (
                "type_invalid",
                f"type must be one of {', '.join(IP_TYPES)}",
                bad_request_failure(),
            )
        values["type"] = ip_type
    if not values and namespace is None and not allow_empty:
        return "nothing_to_update", "Every field resolved to an empty value", bad_request_failure()
    return SplitValues(values, namespace)


# The looked-up name is never repeated: it can come from a device attribute.
LOOKUP_MESSAGES = {
    "namespace_not_found": "The namespace was not found in Nautobot",
    "role_not_found": "The role was not found for IP addresses in Nautobot",
    "status_not_found": "The status was not found for IP addresses in Nautobot",
}


async def _role_id(common: DeviceCommonService, name: str) -> str:
    role_id = await common.resolve_role_id_for_content_type(name, IP_CONTENT_TYPE)
    if role_id is None:
        raise ValueError(LOOKUP_MESSAGES["role_not_found"])
    return role_id


async def _status_id(common: DeviceCommonService, name: str) -> str:
    return await common.resolve_status_id(name, content_type=IP_CONTENT_TYPE)


# field -> (error code, resolver turning a name into the id Nautobot expects)
_LOOKUPS: dict[str, tuple[str, Callable[[DeviceCommonService, str], Awaitable[str]]]] = {
    "namespace": ("namespace_not_found", lambda common, name: common.resolve_namespace_id(name)),
    "role": ("role_not_found", _role_id),
    "status": ("status_not_found", _status_id),
}


async def resolve_ids(
    common: DeviceCommonService, plan: Plan, cache: dict[tuple[str, str], str | Exception]
) -> Plan | tuple[str, Exception]:
    """Replace namespace/role/status names by ids; each distinct name is looked up once."""
    values = dict(plan.values)
    namespace = plan.namespace
    for field, (code, resolver) in _LOOKUPS.items():
        name = namespace if field == "namespace" else values.get(field)
        if name is None:
            continue
        key = (field, name)
        if key not in cache:
            try:
                cache[key] = await resolver(common, name)
            except Exception as exc:
                cache[key] = exc
        found = cache[key]
        if isinstance(found, Exception):
            return code, found
        if field == "namespace":
            namespace = found
        else:
            values[field] = found
    return Plan(plan.device, plan.ip_id, values, namespace)


def lookup_error(code: str, exc: Exception, node_id: str, device: DeviceContext) -> DeviceContext:
    if isinstance(exc, ValueError):
        return failed(
            device,
            node_id=node_id,
            code=code,
            message=LOOKUP_MESSAGES[code],
            failure=not_found_failure(),
        )
    return fail_device_with_error(
        device, device_error_from_exception(
        exc, node_id=node_id, step_id=STEP_ID, keep_text=NAUTOBOT_TEXT
    )
    )


def parent_finder(
    client: CredentialsBoundNautobotClient, namespace_id: str
) -> Callable[[str], Awaitable[str]]:
    """Lookup of the most specific prefix of the target namespace that holds a host address."""

    async def rest_get(endpoint: str) -> Any:
        return await client.rest_request(endpoint=endpoint, method="GET")

    async def find_parent(host: str) -> str:
        prefix_id, _ = await find_containing_prefix(
            rest_get, host, namespace_id, namespace_label="the target namespace"
        )
        return prefix_id

    return find_parent


def write_error(exc: Exception, node_id: str) -> DeviceError:
    """The device error for a failed lookup or write of one address."""
    if isinstance(exc, LookupFailure):
        return DeviceError(
            node_id=node_id,
            step_id=STEP_ID,
            code=exc.code,
            message=str(exc),
            failure=exc.failure,
        )
    if isinstance(exc, NautobotNotFoundError):
        return DeviceError(
            node_id=node_id,
            step_id=STEP_ID,
            code="ip_not_found",
            message="The IP address was not found in Nautobot",
            failure=not_found_failure(),
        )
    return device_error_from_exception(
        exc, node_id=node_id, step_id=STEP_ID, keep_text=NAUTOBOT_TEXT
    )
