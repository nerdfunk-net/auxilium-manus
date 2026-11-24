"""Per-address values for the "IP addresses from interfaces" mode of update-nautobot-ip.

``dns_name`` and ``description`` may differ per address. Besides the usual device ``{path}``
expressions they accept these tokens, filled in for each address:

- ``{ip.address}``: the address with its mask length, for example ``10.1.2.3/24``
- ``{ip.host}``: the address without the mask length
- ``{interface.name}``: the interface that carries it (the first one when it is on several)
- ``{interface.slug}``: that name as a DNS label (``Gi0/0.100`` -> ``gi0-0-100``), because a DNS
  name cannot hold ``/``

A token value never carries braces, so it cannot smuggle in a placeholder of its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from models.workflow_context import DeviceContext
from services.workflow_context.attribute_path import resolve_device_attribute
from services.workflow_context.secret_fields import REDACTED_PLACEHOLDER
from workflow_steps.common.nautobot_plan_fields import PlanError, bad_request_failure
from workflow_steps.common.update_field_expression import resolve_update_field_expression

_PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_.]+)\}")
_WHOLE_EXPRESSION = re.compile(r"^\{[^{}]+\}$")
_NOT_A_LABEL_CHAR = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class AddressRef:
    """One IP address found on an interface of the device."""

    id: str
    address: str
    interface_name: str
    interface_id: str

    @property
    def host(self) -> str:
        return self.address.split("/", 1)[0]


def _clean(value: str) -> str:
    """A token value without braces and NUL bytes (it is not allowed to open a placeholder)."""
    return value.replace("{", "").replace("}", "").replace("\x00", "")


def _slug(name: str) -> str:
    return _NOT_A_LABEL_CHAR.sub("-", name.lower()).strip("-")


def _tokens(ref: AddressRef) -> dict[str, str]:
    return {
        "{ip.address}": _clean(ref.address),
        "{ip.host}": _clean(ref.host),
        "{interface.name}": _clean(ref.interface_name),
        "{interface.slug}": _slug(_clean(ref.interface_name)),
    }


def _error(field: str, raw: str, kind: str) -> PlanError:
    if kind == "secret":
        message = f"{field} expression {raw!r} points to a secret, which this step does not copy"
        return f"{field}_is_secret", message, bad_request_failure()
    return (
        f"{field}_unresolved",
        f"{field} expression {raw!r} resolved to nothing",
        bad_request_failure(),
    )


def render_address_value(
    raw: str,
    device: DeviceContext,
    ref: AddressRef,
    *,
    field: str,
    run_id: str | None = None,
) -> str | PlanError:
    """The value of ``field`` for one address, or ``(code, message, failure)``.

    An unresolved placeholder is an error, never silently empty text, and a value taken from a
    secret is refused (the value is copied into a Nautobot request and error text).
    """
    text = raw
    for token, value in _tokens(ref).items():
        text = text.replace(token, value)
    if "{" not in text:
        return text.strip()

    if _WHOLE_EXPRESSION.match(text.strip()):
        # A whole {path} (optionally with | default('...')) resolves like in the manual mode.
        value = resolve_update_field_expression(
            device=device, field_key=field, raw_value=text, run_id=run_id, reveal_secrets=False
        )
        if value == REDACTED_PLACEHOLDER:
            return _error(field, raw, "secret")
        if value is None:
            return _error(field, raw, "unresolved")
        return value.strip()

    failure: list[PlanError] = []

    def substitute(match: re.Match[str]) -> str:
        value = resolve_device_attribute(device, match.group(1), reveal_secrets=False)
        if value == REDACTED_PLACEHOLDER:
            failure.append(_error(field, raw, "secret"))
            return ""
        if value is None:
            failure.append(_error(field, raw, "unresolved"))
            return ""
        return _clean(value)

    rendered = _PLACEHOLDER.sub(substitute, text)
    if failure:
        return failure[0]
    if "{" in rendered or "}" in rendered:
        return _error(field, raw, "unresolved")
    return rendered.strip()
