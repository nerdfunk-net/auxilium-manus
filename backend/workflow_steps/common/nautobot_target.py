"""The Nautobot device an ``explicit`` ``device_identifier`` names (W5-02, D7).

``update-nautobot-device`` (Update Device) and ``update-config-context`` (Update Config Context)
both offer ``device_identifier.mode = explicit``: one device named in the config instead of the
devices of the context. Both resolve it like a context device, through the strict
``resolve_nautobot_device_id`` (two devices of one name are an error, never a first match).
"""

from __future__ import annotations

from typing import Any

from models.failure import FailureInfo
from models.workflow_context import DeviceContext, DeviceError
from workflow_steps.common.device_outcomes import fail_device_with_error
from workflow_steps.common.partial_outcomes import NAUTOBOT_TEXT, device_error_from_exception

_IDENTIFIER_KEYS = ("id", "name", "ip_address")
_IDENTIFIER_MODES = ("from_context", "explicit")


def parse_identifier_mode(raw_identifier: Any, *, step_id: str) -> str:
    """``from_context`` (default) or ``explicit``; any other text is a config error (W5-14).

    A mistyped mode ("explicti") used to mean ``from_context``, the opposite of what was meant.
    """
    raw = raw_identifier if isinstance(raw_identifier, dict) else {}
    mode = str(raw.get("mode") or "from_context").strip().lower()
    if mode not in _IDENTIFIER_MODES:
        raise ValueError(
            f"{step_id}: device_identifier.mode must be one of {', '.join(_IDENTIFIER_MODES)}"
        )
    return mode


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


def target_failure(
    *,
    device_key: str,
    device: DeviceContext | None,
    node_id: str,
    step_id: str,
    code: str | None = None,
    message: str | None = None,
    exc: Exception | None = None,
    failure: FailureInfo | None = None,
) -> tuple[str, DeviceContext, bool]:
    """``(device_key, failed device, False)`` for a device the step could not update.

    The error is built from ``code`` / ``message`` / ``failure`` or, when given, from ``exc``
    (Nautobot text kept, anything else reduced to the class name). An explicit target that is
    not a context device (``device`` is None) becomes a FAILED placeholder named by the key.
    """
    from_exc = (
        device_error_from_exception(exc, node_id=node_id, step_id=step_id, keep_text=NAUTOBOT_TEXT)
        if exc is not None
        else None
    )
    error_code = code or (from_exc.code if from_exc else "error")
    error_message = message or (from_exc.message if from_exc else "Unknown error")
    failure = failure or (from_exc.failure if from_exc else None)

    error = DeviceError(
        node_id=node_id, step_id=step_id, code=error_code, message=error_message, failure=failure
    )
    target = (
        device
        if device is not None
        else DeviceContext(id=device_key, name=device_key, hostname=device_key, source="nautobot")
    )
    return device_key, fail_device_with_error(target, error), False
