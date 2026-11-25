"""The ISE create payload of add-to-ise, its sealed copy and the request record."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from models.workflow_context import (
    Capability,
    DeviceContext,
)
from services.workflow_context.secret_fields import seal_secret
from workflow_steps.add_to_ise.fields import (
    ResolvedFields,
)
from workflow_steps.common.request_record import append_request_record

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


ISE_CREATE_ENDPOINT = "/ers/config/networkdevice"


def build_create_payload(resolved: ResolvedFields) -> dict[str, Any]:
    device_payload: dict[str, Any] = {
        "name": resolved.name,
        "NetworkDeviceIPList": [{"ipaddress": resolved.ip_host, "mask": resolved.mask}],
        "tacacsSettings": {
            "sharedSecret": resolved.key,
            "connectModeOptions": resolved.single_connect_mode,
        },
    }
    if resolved.description:
        device_payload["description"] = resolved.description
    if resolved.device_groups:
        device_payload["NetworkDeviceGroupList"] = resolved.device_groups
    return device_payload


def sealed_payload(device_payload: dict[str, Any], resolved_key: str) -> dict[str, Any]:
    return {
        **device_payload,
        "tacacsSettings": {
            **device_payload["tacacsSettings"],
            "sharedSecret": seal_secret(resolved_key),
        },
    }


def with_request_record(
    device: DeviceContext,
    *,
    node_id: str,
    device_payload: dict[str, Any],
    resolved_key: str,
    response: dict[str, Any],
    ok: bool,
) -> DeviceContext:
    """Record the create request and ISE's response for the detail view.

    The shared secret is sealed first so the marker-based redaction in
    ``append_request_record`` replaces it — no key material is stored.
    """
    return append_request_record(
        device,
        node_id=node_id,
        target="Cisco ISE",
        method="POST",
        endpoint=ISE_CREATE_ENDPOINT,
        request={"NetworkDevice": sealed_payload(device_payload, resolved_key)},
        response=response,
        ok=ok,
    )


def enrich_device_after_create(
    device: DeviceContext,
    device_payload: dict[str, Any],
    created: dict[str, Any],
    resolved_key: str,
    node_id: str,
) -> DeviceContext:
    sealed_ise_payload = sealed_payload(device_payload, resolved_key)
    attribute_bags = {
        **device.attribute_bags,
        "ise": {**sealed_ise_payload, "id": created.get("id"), "is_group_or_prefix": False},
        "tacacs": {"shared_secret": seal_secret(resolved_key)},
    }
    enriched = device.model_copy(
        update={
            "attribute_bags": attribute_bags,
            "capabilities": device.capabilities | {Capability.ATTRIBUTES},
        }
    )
    return with_request_record(
        enriched,
        node_id=node_id,
        device_payload=device_payload,
        resolved_key=resolved_key,
        response=created,
        ok=True,
    )
