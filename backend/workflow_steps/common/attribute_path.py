"""Resolve dot-path attribute values from a DeviceContext."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from models.workflow_context import DeviceContext
from services.workflow_context.secret_fields import (
    REDACTED_PLACEHOLDER,
    is_sealed_secret,
    unwrap_secret,
)

_DEVICE_SCALAR_FIELDS = frozenset(
    {
        "id",
        "name",
        "hostname",
        "platform",
        "network_driver",
        "primary_ip4",
        "source",
        "source_id",
    }
)

DEVICE_SCALAR_FIELDS = _DEVICE_SCALAR_FIELDS

DEBUG_LOGS_METADATA_SUFFIX = ".debug_logs"


class AttributeState(str, Enum):
    """Existence/emptiness classification for an attribute path resolution.

    Distinguishes "the key isn't there at all" (ABSENT) from "the key is
    there but holds null" (NULL) from "the key holds an empty string/list/
    dict" (EMPTY) from "the key holds real content" (PRESENT) — needed so
    steps like route-on-attribute can route on `{absent}` / `{null}` /
    `{empty}` / `{exists}` instead of only matching literal string values.
    """

    ABSENT = "absent"
    NULL = "null"
    EMPTY = "empty"
    PRESENT = "present"


_MISSING = object()

# Reserved namespace name for a step's parsed output (DeviceContext.parsed),
# mirroring the "parsed" namespace Jinja rendering already exposes via
# build_jinja_context — kept separate from attribute_bags so a step like
# parse-cisco-config's output_key can't collide with an attribute bag name.
_PARSED_NAMESPACE = "parsed"


def _namespace_bag(device: DeviceContext, bag_name: str) -> dict[str, Any] | None:
    """Look up a namespaced bag by name: "parsed" reads DeviceContext.parsed,
    anything else reads DeviceContext.attribute_bags."""
    if bag_name == _PARSED_NAMESPACE:
        return device.parsed or None
    return device.attribute_bags.get(bag_name)


# A path segment like "access_lists[name=MGMT_100]" — navigate to the
# "access_lists" list, then continue traversal from the first item whose
# "name" field stringifies to "MGMT_100". Lets a dotted path reach into a
# specific object inside a list (rather than only ever ending AT a list),
# e.g. "parsed.cisco_config.access_lists[name=MGMT_100].entries" to check
# membership within one ACL's entries instead of across all ACLs.
_FILTER_SEGMENT_RE = re.compile(r"^(?P<key>[^\[\]]+)\[(?P<field>[^\[\]=]+)=(?P<value>[^\[\]]*)\]$")


def _split_path_segments(path: str) -> list[str]:
    """Split on "." but not inside a "[...]" filter segment, so a filter
    value containing a dot (e.g. an IP address) isn't split apart."""
    segments: list[str] = []
    current: list[str] = []
    depth = 0
    for char in path:
        if char == "[":
            depth += 1
            current.append(char)
        elif char == "]":
            depth = max(0, depth - 1)
            current.append(char)
        elif char == "." and depth == 0:
            segments.append("".join(current))
            current = []
        else:
            current.append(char)
    segments.append("".join(current))
    return segments


def _find_filtered_item(items: Any, field: str, value: str) -> Any | None:
    """Return the first dict in ``items`` whose ``field`` (itself a dotted
    path, resolved via ``_traverse_path``) stringifies to ``value``."""
    if not isinstance(items, list):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        candidate = _traverse_path(item, field)
        if candidate is None or isinstance(candidate, (dict, list)):
            continue
        if str(candidate) == value:
            return item
    return None


def _traverse_path(root: Any, path: str) -> Any:
    current = root
    for segment in _split_path_segments(path):
        if current is None:
            return None
        match = _FILTER_SEGMENT_RE.match(segment)
        if match:
            if not isinstance(current, dict):
                return None
            current = _find_filtered_item(
                current.get(match.group("key")), match.group("field"), match.group("value")
            )
            continue
        if isinstance(current, dict):
            current = current.get(segment)
            continue
        return None
    return current


def _traverse_path_raw(root: Any, path: str) -> Any:
    """Like ``_traverse_path`` but returns ``_MISSING`` when a key along the
    path doesn't exist, instead of collapsing that case into ``None``."""
    current = root
    for segment in _split_path_segments(path):
        match = _FILTER_SEGMENT_RE.match(segment)
        if match:
            if not isinstance(current, dict) or match.group("key") not in current:
                return _MISSING
            found = _find_filtered_item(
                current[match.group("key")], match.group("field"), match.group("value")
            )
            if found is None:
                return _MISSING
            current = found
            continue
        if not isinstance(current, dict) or segment not in current:
            return _MISSING
        current = current[segment]
    return current


def _classify_value(value: Any) -> tuple[AttributeState, str | None]:
    if value is None:
        return AttributeState.NULL, None
    if isinstance(value, (dict, list)):
        return (AttributeState.PRESENT, None) if len(value) > 0 else (AttributeState.EMPTY, None)
    text = str(value).strip()
    if not text:
        return AttributeState.EMPTY, None
    return AttributeState.PRESENT, text


def _stringify(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def build_device_value_context(
    device: DeviceContext,
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build a namespaced lookup tree for attribute path resolution."""
    from workflow_steps.common.device_template import build_template_context

    context = build_template_context(device, run_id=run_id)
    for bag_name, bag_value in device.attribute_bags.items():
        if bag_name not in context:
            context[bag_name] = dict(bag_value)
    if device.parsed:
        context[_PARSED_NAMESPACE] = dict(device.parsed)
    context["capabilities"] = sorted(cap.value for cap in device.capabilities)
    context["status"] = device.status.value
    return context


def resolve_device_value(
    device: DeviceContext,
    attribute_path: str,
    *,
    run_id: str | None = None,
) -> Any:
    """Resolve a dot path and return the raw value (including dict/list)."""
    path = attribute_path.strip()
    if not path:
        return None

    context = build_device_value_context(device, run_id=run_id)

    if path.startswith("device."):
        field_name = path[len("device.") :]
        if "." not in field_name and field_name in _DEVICE_SCALAR_FIELDS:
            return getattr(device, field_name)
        return _traverse_path(context, path)

    if "." not in path and path in _DEVICE_SCALAR_FIELDS:
        return getattr(device, path)

    if "." in path:
        return _traverse_path(context, path)

    if path in context:
        return context[path]

    bag = device.attribute_bags.get(path)
    if bag is not None:
        return dict(bag)
    return None


def _resolve_leaf(value: Any, *, reveal_secrets: bool) -> str | None:
    """Stringify a resolved bag leaf, unwrapping (or redacting) a sealed secret."""
    if is_sealed_secret(value):
        if not reveal_secrets:
            return REDACTED_PLACEHOLDER
        return unwrap_secret(value)
    return _stringify(value)


def resolve_device_attribute(
    device: DeviceContext, attribute_path: str, *, reveal_secrets: bool = True
) -> str | None:
    """Resolve a dot path against device scalars and namespaced attribute bags.

    A leading ``parsed.`` segment reads ``DeviceContext.parsed`` (the output
    of steps like ``parse-cisco-config``, ``render-jinja-template``,
    ``filter-output``) instead of ``attribute_bags`` — e.g.
    ``parsed.cisco_config.hostname``. Like any other bag, only scalar leaves
    resolve to a string here; a leaf holding a dict/list (e.g. a list of
    parsed AAA servers) resolves to ``None`` — use ``resolve_device_value``
    or ``resolve_device_attribute_state`` (``{exists}``/``{empty}``) for
    those instead of expecting a literal-value match.

    ``reveal_secrets`` controls what happens when the resolved leaf is a
    sealed secret envelope (see ``services.workflow_context.secret_fields``):
    ``True`` (the default — for trusted consumers like Jinja rendering and
    ISE-update expressions) decrypts it in-memory for this call; ``False``
    (for generic/bulk callers such as ``update-attribute`` and
    ``log-message``, which must never rehydrate or re-expose a secret)
    returns ``REDACTED_PLACEHOLDER`` instead.
    """
    path = attribute_path.strip()
    if not path:
        return None

    if path.startswith("device."):
        field_name = path[len("device.") :].split(".", 1)[0]
        if field_name not in _DEVICE_SCALAR_FIELDS:
            return None
        if "." in path[len("device.") :]:
            return None
        return _stringify(getattr(device, field_name))

    if "." not in path and path in _DEVICE_SCALAR_FIELDS:
        return _stringify(getattr(device, path))

    if "." in path:
        bag_name, remainder = path.split(".", 1)
        bag = _namespace_bag(device, bag_name)
        if bag is None:
            return None
        raw = _traverse_path(bag, remainder)
        return _resolve_leaf(raw, reveal_secrets=reveal_secrets)

    bag = _namespace_bag(device, path)
    if bag is None:
        return None
    if isinstance(bag, dict) and len(bag) == 1:
        only_value = next(iter(bag.values()))
        return _resolve_leaf(only_value, reveal_secrets=reveal_secrets)
    return None


def resolve_device_attribute_state(
    device: DeviceContext, attribute_path: str
) -> tuple[AttributeState, str | None]:
    """Resolve a dot path and classify it as absent/null/empty/present.

    Unlike ``resolve_device_attribute``, this distinguishes a path whose key
    doesn't exist at all (``ABSENT``) from one whose value is explicitly
    ``None`` (``NULL``) from one whose value is an empty string/list/dict
    (``EMPTY``) — needed for steps that route on those states rather than on
    a literal string value (for example: "was a TACACS+ key ever set?", or
    "does this device have any parsed AAA servers at all?").

    A leading ``parsed.`` segment reads ``DeviceContext.parsed`` — see
    ``resolve_device_attribute`` for the same convention. This is how
    ``route-on-attribute`` can branch on ``{exists}``/``{empty}``/``{absent}``
    for a parsed list/dict value (e.g. ``parsed.cisco_config.aaa_servers.servers``)
    even though the literal contents of that list can't be matched as a single
    string value.
    """
    path = attribute_path.strip()
    if not path:
        return AttributeState.ABSENT, None

    if path.startswith("device."):
        field_name = path[len("device.") :].split(".", 1)[0]
        if field_name not in _DEVICE_SCALAR_FIELDS or "." in path[len("device.") :]:
            return AttributeState.ABSENT, None
        return _classify_value(getattr(device, field_name))

    if "." not in path and path in _DEVICE_SCALAR_FIELDS:
        return _classify_value(getattr(device, path))

    if "." in path:
        bag_name, remainder = path.split(".", 1)
        bag = _namespace_bag(device, bag_name)
        if bag is None:
            return AttributeState.ABSENT, None
        raw = _traverse_path_raw(bag, remainder)
        if raw is _MISSING:
            return AttributeState.ABSENT, None
        return _classify_value(raw)

    bag = _namespace_bag(device, path)
    if bag is None:
        return AttributeState.ABSENT, None
    if isinstance(bag, dict):
        if len(bag) == 0:
            return AttributeState.EMPTY, None
        if len(bag) == 1:
            return _classify_value(next(iter(bag.values())))
        return AttributeState.PRESENT, None
    return _classify_value(bag)
