"""Discover candidate attribute paths from a past run's persisted, redacted output.

Separate from ``attribute_path.py`` on purpose: that module resolves one
already-known path against one *live* ``DeviceContext`` during step execution
(secret/error-aware). This module instead enumerates what paths *could* be
typed, by walking every ancestor step's persisted ``WorkflowStepResult.output``
for a run — a different concern with its own dict/list-union and
discriminator-inference algorithm. It only depends on ``attribute_path.py``'s
public surface (``DEVICE_SCALAR_FIELDS``), never its private traversal
helpers: building a filter segment is just string formatting, only
*consuming* one needs the private regex.
"""

from __future__ import annotations

from typing import Any

from core.models.runs import WorkflowStepResult
from models.attribute_path import AttributePathNode
from models.workflow_context import DeviceContext, WorkflowContext
from services.workflow_context.attribute_path import DEVICE_SCALAR_FIELDS, unwrap_singleton_list
from services.workflow_context.merge import merge_device_contexts

# Caps how many discriminated branches a single list-of-dicts node expands
# into, so a large inventory-style list doesn't blow up the tree response.
MAX_LIST_ITEM_BRANCHES = 25

# Preferred discriminator field names, in order, used only as a tie-break
# among candidates that already fully cover and uniquely identify every item
# — never a requirement.
_PREFERRED_DISCRIMINATOR_NAMES = (
    "name",
    "id",
    "key",
    "address",
    "ip",
    "ip_address",
    "hostname",
    "interface",
    "index",
)

_SCALAR_TYPES = (str, int, float, bool)

_RAW_CONFIG_PLACEHOLDER = "(raw config — not browsable)"


def _looks_like_raw_config(value: Any) -> bool:
    """True when a dict's own keys look like literal CLI config lines rather
    than field names — e.g. Genie's raw ``show running-config`` parse result
    (``get-pyats-running-config``), keyed by lines such as ``"interface Ethernet0/0"``
    or ``"ip address ... secondary"`` (see doc/PYATS_INTEGRATION.md).

    Real structured data — device fields, a parsed-config *model* (Cisco
    Config Parser's ``l3_interfaces`` etc.), attribute bags — never has
    whitespace inside a key; raw CLI line text almost always does. Detected
    dicts are collapsed to a single opaque leaf instead of recursed into, so
    hundreds of raw (and sometimes secret-bearing, e.g. a `username ...
    secret ...` line) CLI lines never turn into clickable "attribute paths"
    in the picker.

    Checked together with ``_looks_like_command_output_bag`` below — a
    multi-word command string (e.g. ``"show version"``) also has whitespace
    in the key, so on its own this heuristic would misfire on run-command's
    own per-command output too; the caller must exclude that case first.
    """
    if not isinstance(value, dict) or not value:
        return False
    return any(isinstance(key, str) and " " in key for key in value)


def _looks_like_command_output_bag(value: Any) -> bool:
    """True when every value in this dict is the normalized ``{"parsed",
    "error"}`` command-result shape (see doc/WORKFLOW-STEPS.md's "Normalized
    command-output parsing") that ``run-command`` (textfsm/genie) and
    ``render-jinja-template`` write at ``parsed.<parsed_output_key>``, keyed
    by the literal command string — e.g. ``{"show version": {"parsed": ...,
    "error": None}}``. A real command string almost always contains a space,
    which would otherwise make ``_looks_like_raw_config`` mistake this for a
    raw CLI config dict and hide it from the picker entirely. Checked first
    so a command-keyed dict is never collapsed to the opaque placeholder.
    """
    if not isinstance(value, dict) or not value:
        return False
    return all(
        isinstance(entry, dict) and "parsed" in entry and set(entry) <= {"parsed", "error"}
        for entry in value.values()
    )


def merge_ancestor_devices(
    step_results: list[WorkflowStepResult],
    ancestor_node_ids: set[str],
) -> tuple[dict[str, DeviceContext], list[str]]:
    """Fold every outcome's devices from ancestor step results into one view.

    ``step_results`` is assumed to already be in ascending ``id`` (execution)
    order — see ``RunRepository.get_step_results_for_run``. When two ancestor
    steps are independent parallel branches that both touch the same device
    (a join, e.g. Run Command and Parse Cisco Config both feeding Update
    Attribute), a later step result is merged with an earlier one for the
    same device id via ``merge_device_contexts`` — the same real merge logic
    ``StepRunner`` uses at a join node at runtime — instead of blindly
    replacing it, so the picker doesn't silently lose one branch's fields
    just because the other branch's step happened to persist second. A
    genuine merge conflict (the same key holding two different values —
    e.g. the same node re-run with different config) falls back to
    last-writer-wins rather than raising, since this only powers a
    best-effort browsing/preview feature. Malformed or missing ``output`` is
    tolerated silently for the same reason.
    """
    merged: dict[str, DeviceContext] = {}
    matched_node_ids: dict[str, None] = {}

    for step_result in step_results:
        if step_result.step_node_id not in ancestor_node_ids:
            continue
        output = step_result.output
        if not isinstance(output, dict):
            continue
        outcomes = output.get("outcomes")
        if not isinstance(outcomes, dict):
            continue

        for outcome in outcomes.values():
            # `outcome` here IS the serialized WorkflowContext directly (see
            # StepRunner._serialize_outcomes: `outcome.name: outcome.context
            # .model_dump(...)`) — there is no nested "context" key.
            if not isinstance(outcome, dict):
                continue
            try:
                context = WorkflowContext.model_validate(outcome)
            except Exception:  # noqa: S112 - tolerate malformed/legacy persisted output
                continue
            matched_node_ids[step_result.step_node_id] = None
            for device_id, device in context.devices.items():
                existing = merged.get(device_id)
                if existing is None:
                    merged[device_id] = device
                    continue
                try:
                    merged[device_id] = merge_device_contexts([existing, device])
                except ValueError:
                    merged[device_id] = device

    return merged, list(matched_node_ids)


def infer_discriminator_key(items: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Pick a top-level scalar field that identifies each item in ``items``.

    Returns ``(key, warning)``. ``warning`` is set when the best available
    key doesn't fully cover or uniquely identify every item — the caller
    still gets a usable (if imperfect) filter key rather than nothing, since
    ``_find_filtered_item`` (the consuming code in ``attribute_path.py``)
    always needs *some* field to filter on. Returns ``(None, None)`` only
    when no item has any scalar field at all.
    """
    if not items:
        return None, None

    candidate_names: set[str] = set()
    for item in items:
        for key, value in item.items():
            if isinstance(value, _SCALAR_TYPES):
                candidate_names.add(key)
    if not candidate_names:
        return None, None

    scores: dict[str, tuple[float, float]] = {}
    for key in candidate_names:
        values = [str(item[key]) for item in items if isinstance(item.get(key), _SCALAR_TYPES)]
        coverage = len(values) / len(items)
        distinctness = len(set(values)) / len(items)
        scores[key] = (coverage, distinctness)

    fully_qualified = sorted(key for key, score in scores.items() if score == (1.0, 1.0))
    if fully_qualified:
        for preferred in _PREFERRED_DISCRIMINATOR_NAMES:
            match = next((key for key in fully_qualified if key.lower() == preferred), None)
            if match is not None:
                return match, None
        return fully_qualified[0], None

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1][0], -kv[1][1], kv[0]))
    best_key = ranked[0][0]
    warning = (
        f"{best_key!r} does not uniquely identify every entry — some items may not be "
        "reachable or a duplicate value may be matched"
    )
    return best_key, warning


def _example_value(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def _first_example(values: list[Any]) -> str | None:
    for value in values:
        example = _example_value(value)
        if example is not None:
            return example
    return None


def _build_node(name: str, path: str, values: list[Any]) -> AttributePathNode:
    dict_values = [value for value in values if isinstance(value, dict)]
    list_values = [value for value in values if isinstance(value, list)]
    scalar_values = [value for value in values if not isinstance(value, (dict, list))]

    # A key observed as different shapes across devices/ancestors is rare;
    # dict > list > scalar is an arbitrary but deterministic tie-break.
    if dict_values:
        if any(
            _looks_like_raw_config(value) and not _looks_like_command_output_bag(value)
            for value in dict_values
        ):
            return AttributePathNode(
                name=name,
                path=path,
                kind="scalar",
                example_value=_RAW_CONFIG_PLACEHOLDER,
            )
        return _build_dict_node(name, path, dict_values)
    if list_values:
        return _build_list_node(name, path, list_values)
    return AttributePathNode(
        name=name,
        path=path,
        kind="scalar",
        example_value=_first_example(scalar_values),
    )


def _build_dict_node(name: str, path: str, dicts: list[dict[str, Any]]) -> AttributePathNode:
    key_order: dict[str, None] = {}
    for d in dicts:
        for key in d:
            key_order[key] = None

    children = [
        _build_node(key, f"{path}.{key}" if path else key, [d[key] for d in dicts if key in d])
        for key in key_order
    ]
    return AttributePathNode(name=name, path=path, kind="dict", children=children)


def _build_list_node(name: str, path: str, lists: list[list[Any]]) -> AttributePathNode:
    # A singleton-scalar list (e.g. ntc-templates' SERIAL/HARDWARE/MAC_ADDRESS
    # "Value List" fields, always one item for a single-chassis device) has
    # only one possible reading — surface it as a clickable scalar leaf
    # instead of a dead-end list node, same shape the resolver now accepts
    # for a real source_path (see unwrap_singleton_list's docstring). Only
    # when *every* device's own list for this key is that exact shape —
    # otherwise fall through to the generic list handling below.
    unwrapped = [unwrap_singleton_list(lst) for lst in lists]
    if lists and all(isinstance(value, _SCALAR_TYPES) for value in unwrapped):
        return AttributePathNode(
            name=name,
            path=path,
            kind="scalar",
            example_value=_first_example(unwrapped),
        )

    items: list[Any] = [item for lst in lists for item in lst]

    if items and all(isinstance(item, dict) for item in items):
        key, warning = infer_discriminator_key(items)
        if key is not None:
            groups: dict[str, list[dict[str, Any]]] = {}
            for item in items:
                value = item.get(key)
                if isinstance(value, _SCALAR_TYPES):
                    groups.setdefault(str(value), []).append(item)
            children = [
                _build_dict_node(f"{key}={value}", f"{path}[{key}={value}]", groups[value])
                for value in sorted(groups)[:MAX_LIST_ITEM_BRANCHES]
            ]
            return AttributePathNode(
                name=name,
                path=path,
                kind="list",
                item_count=len(items),
                discriminator_warning=warning,
                children=children,
            )

    return AttributePathNode(
        name=name,
        path=path,
        kind="list",
        item_count=len(items),
        example_value=_first_example(items),
    )


def build_attribute_path_tree(devices: dict[str, DeviceContext]) -> list[AttributePathNode]:
    """Build the device/parsed/<bag-name> namespace tree for a merged device view.

    Pure function — no DB, no I/O — independently testable against
    hand-built ``DeviceContext`` fixtures.
    """
    device_list = list(devices.values())

    device_children = [
        AttributePathNode(
            name=field_name,
            path=f"device.{field_name}",
            kind="scalar",
            example_value=_first_example([getattr(device, field_name) for device in device_list]),
        )
        for field_name in sorted(DEVICE_SCALAR_FIELDS)
    ]
    nodes = [AttributePathNode(name="device", path="device", kind="dict", children=device_children)]

    parsed_dicts = [device.parsed for device in device_list if device.parsed]
    if parsed_dicts:
        nodes.append(_build_dict_node("parsed", "parsed", parsed_dicts))

    bag_name_order: dict[str, None] = {}
    for device in device_list:
        for bag_name in device.attribute_bags:
            bag_name_order[bag_name] = None

    for bag_name in bag_name_order:
        bag_dicts = [
            device.attribute_bags[bag_name]
            for device in device_list
            if bag_name in device.attribute_bags
        ]
        nodes.append(_build_dict_node(bag_name, bag_name, bag_dicts))

    return nodes
