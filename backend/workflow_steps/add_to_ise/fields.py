"""Resolution of the per-device ISE fields (name, address, key, groups) for add-to-ise."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from models.workflow_context import (
    DeviceContext,
)
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER
from workflow_steps.add_to_ise.parse import (
    CONNECT_MODE_OFF,
    STEP_ID,
    ParsedConfig,
    effective_primary_ip4,
    extract_ip_host,
    extract_ip_mask,
)
from workflow_steps.common.value_expression import (
    resolve_template_if_present,
    resolve_update_field_expression,
)

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedFields:
    name: str
    ip_host: str
    mask: int
    key: str
    description: str
    device_groups: list[str]
    single_connect_mode: str = CONNECT_MODE_OFF


def resolve_device_groups(
    device: DeviceContext, raw_groups: list[str]
) -> list[str] | tuple[str, str]:
    """Resolve each ``device_groups`` entry, or return ``(failure_code, message)``.

    An entry may mix text and several ``{path}`` tokens (``{a}#{b}``), each
    substituted in place. A token whose path does not exist for the device fails
    it; a blank value is substituted as ``""``, and an entry that ends up empty
    contributes no group (ISE then applies its default root).
    """
    resolved: list[str] = []
    for raw in raw_groups:
        value, missing = resolve_template_if_present(device=device, raw_value=raw)
        if value is None:
            return (
                "device_group_unresolved",
                (
                    f"device_groups entry '{raw}' did not resolve for '{device.name}': "
                    f"{missing} does not exist (available attribute bags: "
                    f"{sorted(device.attribute_bags)})"
                ),
            )
        if value:
            resolved.append(value)
    return resolved


def secret_refused(field: str) -> tuple[str, str]:
    """``(code, message)``: a sealed secret must not be copied into any ISE field but the key."""
    return (
        f"{field}_is_secret",
        f"{field} expression points to a sealed secret; only new_key may read one",
    )


def resolve_device_fields(
    device: DeviceContext,
    cfg: ParsedConfig,
    run_id: str | None,
) -> ResolvedFields | tuple[str, str]:
    """Return resolved fields or ``(failure_code, failure_message)``."""
    resolved_name = resolve_update_field_expression(
        device=device,
        field_key="device_name",
        raw_value=cfg.raw_device_name,
        run_id=run_id,
        reveal_secrets=False,
    )
    if resolved_name == REDACTED_PLACEHOLDER:
        return secret_refused("device_name")
    if not resolved_name:
        return (
            "device_name_unresolved",
            (
                f"device_name expression '{cfg.raw_device_name}' did not resolve to a "
                f"value for '{device.name}'"
            ),
        )

    resolved_ip = resolve_update_field_expression(
        device=device,
        field_key="ip_address",
        raw_value=cfg.raw_ip_address,
        run_id=run_id,
        reveal_secrets=False,
    )
    if resolved_ip == REDACTED_PLACEHOLDER:
        return secret_refused("ip_address")
    if not resolved_ip and "primary_ip4" in cfg.raw_ip_address:
        resolved_ip = effective_primary_ip4(device)

    if not resolved_ip:
        return (
            "ip_address_unresolved",
            (
                f"ip_address expression '{cfg.raw_ip_address}' did not resolve to a "
                f"value for '{device.name}' (device.primary_ip4={device.primary_ip4!r}, "
                f"available attribute bags: {sorted(device.attribute_bags)})"
            ),
        )

    ip_host = extract_ip_host(resolved_ip)
    if not ip_host:
        return (
            "ip_address_invalid",
            (
                f"ip_address resolved to '{resolved_ip}' for '{device.name}', which is "
                "not a valid IP address"
            ),
        )

    mask = extract_ip_mask(
        resolved_ip, ip_host, cfg.netmask_override, use_address_prefix=cfg.use_address_prefix
    )
    if mask is None:
        return (
            "netmask_invalid",
            (
                f"netmask for '{resolved_ip}' on '{device.name}' is not a valid prefix length "
                f"(netmask_override={cfg.netmask_override!r})"
            ),
        )

    resolved_key = resolve_update_field_expression(
        device=device,
        field_key="new_key",
        raw_value=cfg.raw_new_key,
        run_id=run_id,
        reveal_secrets=True,  # the key goes to ISE, the system that holds it
    )
    if not resolved_key:
        return (
            "tacacs_key_unresolved",
            (
                f"new_key expression '{cfg.raw_new_key}' did not resolve to a value for "
                f"'{device.name}' (available attribute bags: {sorted(device.attribute_bags)})"
            ),
        )

    # description is optional: an expression that resolves to nothing just
    # leaves the ISE description empty instead of failing the device.
    resolved_description = resolve_update_field_expression(
        device=device,
        field_key="description",
        raw_value=cfg.description,
        run_id=run_id,
        reveal_secrets=False,
    )
    if resolved_description == REDACTED_PLACEHOLDER:
        return secret_refused("description")
    if cfg.description and not resolved_description:
        logger.warning(
            "%s: description expression '%s' did not resolve for '%s'; creating without one",
            STEP_ID,
            cfg.description,
            device.name,
        )

    resolved_groups = resolve_device_groups(device, cfg.device_groups)
    if isinstance(resolved_groups, tuple):
        return resolved_groups

    return ResolvedFields(
        name=resolved_name,
        ip_host=ip_host,
        mask=mask,
        key=resolved_key,
        description=resolved_description or "",
        device_groups=resolved_groups,
        single_connect_mode=cfg.single_connect_mode,
    )
