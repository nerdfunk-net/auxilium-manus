"""Parsing of the add-to-ise step config (groups, connect mode, IP and mask)."""

from __future__ import annotations

import ipaddress
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from services.workflow_context.secret_expression import require_secret_expression
from workflow_steps.common.step_flags import parse_bool_flag

if TYPE_CHECKING:
    pass


logger = logging.getLogger(__name__)


STEP_ID = "add-to-ise"
CONNECT_MODE_OFF = "OFF"
_CONNECT_MODES = frozenset({CONNECT_MODE_OFF, "ON_LEGACY", "ON_DRAFT_COMPLIANT"})


@dataclass(frozen=True)
class ParsedConfig:
    source_id: str
    raw_device_name: str
    raw_ip_address: str
    raw_new_key: str
    description: str
    device_groups: list[str]
    netmask_override: int | None = None
    create_missing_groups: bool = False
    single_connect_mode: str = CONNECT_MODE_OFF
    use_address_prefix: bool = False


HOST_MASK = 32
MAX_MASK_BY_VERSION = {4: 32, 6: 128}


def _parse_device_groups(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"{STEP_ID}: device_groups must be a list")
    return [str(item).strip() for item in raw if str(item).strip()]


def _parse_single_connect_mode(raw: Any) -> str:
    """Validate the ``single_connect_mode`` config value; blank means ``OFF``."""
    mode = str(raw or "").strip() or CONNECT_MODE_OFF
    if mode not in _CONNECT_MODES:
        raise ValueError(
            f"{STEP_ID}: single_connect_mode must be one of {sorted(_CONNECT_MODES)}, got '{raw}'"
        )
    return mode


def parse_netmask_override(raw: Any) -> int | None:
    """Parse the optional ``netmask_override`` config value (``"32"``, ``"/32"``, ``32``)."""
    if raw is None:
        return None
    text = str(raw).strip().lstrip("/").strip()
    if not text:
        return None
    if not (text.isascii() and text.isdigit()) or int(text) > MAX_MASK_BY_VERSION[6]:
        raise ValueError(
            f"{STEP_ID}: netmask_override must be a prefix length such as 32 or /24, got '{raw}'"
        )
    return int(text)


def extract_ip_mask(
    raw: str, ip_host: str, override: int | None, *, use_address_prefix: bool = False
) -> int | None:
    """Pick the mask for *ip_host*: override, else (opt-in) the ``/nn`` suffix of *raw*, else /32.

    The suffix is ignored by default: Nautobot stores a device's primary IP with the
    interface prefix (``10.0.0.1/24``), and an ISE entry with that mask would cover the
    whole subnet instead of the one device.

    Returns ``None`` when the chosen mask is not valid for the address family.
    """
    mask = override
    if mask is None and use_address_prefix:
        _, _, suffix = raw.partition("/")
        suffix = suffix.strip()
        if suffix:
            if not (suffix.isascii() and suffix.isdigit()):
                return None
            mask = int(suffix)
    if mask is None:
        mask = HOST_MASK
    if mask > MAX_MASK_BY_VERSION[ipaddress.ip_address(ip_host).version]:
        return None
    return mask


def extract_ip_host(raw: str) -> str | None:
    """Return the bare host address for a resolved ``ip_address`` value.

    Accepts either a plain address (``10.0.0.1``) or a CIDR-suffixed one
    (``10.0.0.1/24``) and returns ``None`` if the host portion isn't a valid
    IPv4/IPv6 address.
    """
    candidate = raw.split("/", 1)[0].strip()
    try:
        ipaddress.ip_address(candidate)
    except ValueError:
        return None
    return candidate


def parse_config(config: dict[str, Any]) -> ParsedConfig:
    source_id = (config.get("ise_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{STEP_ID}: ise_source_id is not configured")

    raw_device_name = (config.get("device_name") or "").strip()
    if not raw_device_name:
        raise ValueError(f"{STEP_ID}: device_name is not configured")

    raw_ip_address = (config.get("ip_address") or "").strip()
    if not raw_ip_address:
        raise ValueError(f"{STEP_ID}: ip_address is not configured")

    raw_new_key = (config.get("new_key") or "").strip()
    if not raw_new_key:
        raise ValueError(f"{STEP_ID}: new_key is not configured")
    raw_new_key = require_secret_expression(raw_new_key, field="new_key", step_id=STEP_ID)

    description = str(config.get("description") or "").strip()
    device_groups = _parse_device_groups(config.get("device_groups"))

    netmask_override = parse_netmask_override(config.get("netmask_override"))

    return ParsedConfig(
        source_id=source_id,
        raw_device_name=raw_device_name,
        raw_ip_address=raw_ip_address,
        raw_new_key=raw_new_key,
        description=description,
        device_groups=device_groups,
        netmask_override=netmask_override,
        create_missing_groups=parse_bool_flag(config, "create_missing_groups"),
        single_connect_mode=_parse_single_connect_mode(config.get("single_connect_mode")),
        use_address_prefix=parse_bool_flag(config, "use_address_prefix"),
    )
