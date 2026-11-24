"""The Nautobot device an ``explicit`` ``device_identifier`` names (W5-02, D7).

``update-nautobot-device`` (Update Device) and ``update-config-context`` (Update Config Context)
both offer ``device_identifier.mode = explicit``: one device named in the config instead of the
devices of the context. Both resolve it like a context device, through the strict
``resolve_nautobot_device_id`` (two devices of one name are an error, never a first match).
"""

from __future__ import annotations

from typing import Any

from models.workflow_context import DeviceContext

_IDENTIFIER_KEYS = ("id", "name", "ip_address")


def parse_explicit_identifier(raw_identifier: Any, *, step_id: str) -> dict[str, str]:
    """The non-empty ``id`` / ``name`` / ``ip_address`` of an explicit identifier.

    Raises ``ValueError`` when none is set: an explicit device without a name is a config error,
    never a device called "explicit".
    """
    raw = raw_identifier if isinstance(raw_identifier, dict) else {}
    identifier = {
        key: text for key in _IDENTIFIER_KEYS if (text := str(raw.get(key) or "").strip())
    }
    if not identifier:
        raise ValueError(
            f"{step_id}: device_identifier.mode 'explicit' needs an id, name or ip_address"
        )
    return identifier


def explicit_device_context(identifier: dict[str, str]) -> DeviceContext:
    """A placeholder device for an explicit identifier, resolved like any context device.

    An ``id`` is trusted only when it is a Nautobot UUID (``source`` is ``nautobot``); otherwise
    the name, then the primary IPv4 address decide.
    """
    explicit_id = identifier.get("id", "")
    explicit_name = identifier.get("name", "")
    return DeviceContext(
        id=explicit_id or "explicit",
        name=explicit_name,
        hostname=explicit_name or explicit_id or "explicit",
        source="nautobot",
        primary_ip4=identifier.get("ip_address") or None,
    )
