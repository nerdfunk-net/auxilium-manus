"""Prompt rendering for the contact-the-ai step.

Like the notification steps it fills ``{devices}``, ``{device_count}``, ``{run_summary}`` and
``{path.to.value}`` (first device). Unlike them, a path that points at a whole dict or list --
``{nautobot}``, ``{nautobot.location}``, ``{parsed.cisco_config.running}`` -- is rendered as compact
JSON instead of an empty string. This is deliberately local to this step: the shared placeholder
resolver, and with it every other step, keeps returning scalars only.

**Nothing is resolved before the sharing policy has looked at its path.** The step applies the same
rules as the interactive assistant (``services/ai_assistant/data_sharing.py``, S5-03), against the
sharing switches of the service user (already ANDed with the operator's ``AI_ALLOWED_DATA``):

* ``device.<field>``: ``name``, ``platform``, ... need *inventory*; ``hostname`` and the primary
  address need *addresses* (which itself needs *inventory*);
* ``nautobot.<attribute>``: the attribute must be in a Nautobot category and that category must be
  shared (basics: inventory; ``serial``, ``interfaces``, ... : addresses; ``custom_fields``;
  ``config_context``). An attribute in no category (``comments``, ...) is never sent;
* any other bag (``custom``, ``parsed``, ``ise``, run inputs, ...): needs *inventory* **and**
  *content*;
* below that, a key that names a category (``custom_fields``, ``config_context``, ``interfaces``,
  ``serial`` ...) is withheld unless its switch is on.

A path the policy withholds fails the step closed (``PromptWithheldError``); nothing is sent. A
whole ``{nautobot}`` bag is the one exception: it is filtered the way the assistant filters it, and
the withheld attribute names are listed in the JSON instead of failing the step.

A structured value is tokenised before it is written into the prompt (``Redactor.tokenize_data``:
secret-named keys and sealed envelopes become ``__SECRET_n__`` tokens, every other string gets the
text redaction), then cut at ``MAX_STRUCTURED_CHARS``.
"""

from __future__ import annotations

import json
import re

from models.workflow_context import WorkflowContext
from services.ai_assistant.data_sharing import (
    DataClass,
    SharingPolicy,
    attribute_class,
    category_of_key,
    filter_nautobot_attributes,
    mask_by_key,
    setting_name,
)
from services.ai_assistant.redaction import Redactor
from services.workflow_context.attribute_path import (
    resolve_device_attribute,
    resolve_device_attribute_raw,
)
from workflow_steps.common.run_message_template import (
    apply_run_placeholders,
    finish_run_placeholders,
)

# One structured placeholder is cut here, on top of the cap on the whole prompt.
MAX_STRUCTURED_CHARS = 20_000

_PLACEHOLDER = re.compile(r"\{([A-Za-z0-9_.]+)\}")

_DEVICE_FIELD_CLASS: dict[str, DataClass] = {
    "id": DataClass.INVENTORY,
    "name": DataClass.INVENTORY,
    "platform": DataClass.INVENTORY,
    "network_driver": DataClass.INVENTORY,
    "source": DataClass.INVENTORY,
    "source_id": DataClass.INVENTORY,
    "hostname": DataClass.ADDRESSES,
    "primary_ip4": DataClass.ADDRESSES,
    "primary_ip4_cidr": DataClass.ADDRESSES,
}


class PromptWithheldError(Exception):
    """A placeholder points at data the sharing policy does not release. The message is fixed
    wording naming the placeholder and the setting, never run data."""


def _need(policy: SharingPolicy, path: str, data_class: DataClass) -> None:
    if not policy.allows(data_class):
        suffix = (
            "" if data_class is DataClass.INVENTORY else " (and 'Inventory and device attributes')"
        )
        raise PromptWithheldError(
            f"{{{path}}} needs the '{setting_name(data_class)}' sharing switch{suffix}"
        )


def _check_nested_keys(policy: SharingPolicy, path: str, keys: list[str]) -> None:
    for key in keys:
        needed = category_of_key(key)
        if needed is not None:
            _need(policy, path, needed)


def check_path(policy: SharingPolicy, path: str) -> None:
    """Raise ``PromptWithheldError`` unless ``path`` may be read into the prompt."""
    parts = path.split(".")
    root = parts[0]
    if root == "device" or (len(parts) == 1 and root in _DEVICE_FIELD_CLASS):
        field = parts[1] if root == "device" and len(parts) > 1 else root
        needed = _DEVICE_FIELD_CLASS.get(field)
        if needed is None or (root == "device" and len(parts) != 2):
            raise PromptWithheldError(f"{{{path}}} is not a device field that can be sent")
        _need(policy, path, needed)
        return
    if root == "nautobot":
        if len(parts) == 1:
            _need(policy, path, DataClass.INVENTORY)  # the bag is filtered, see render_prompt
            return
        needed = attribute_class(parts[1])
        if needed is None:
            raise PromptWithheldError(f"{{{path}}}: '{parts[1]}' is never sent to the AI")
        _need(policy, path, needed)
        _check_nested_keys(policy, path, parts[2:])
        return
    # Any other bag holds arbitrary per-source keys: names and content both have to be shared.
    _need(policy, path, DataClass.INVENTORY)
    _need(policy, path, DataClass.CONTENT)
    _check_nested_keys(policy, path, parts[1:])


_ADDRESS_CHARS = frozenset("0123456789abcdefABCDEF.:%")


def cut_text(text: str, limit: int) -> tuple[str, int]:
    """``text`` cut to at most ``limit`` characters and the number of characters left out.

    The cut never ends inside what could be an address: a trailing run of digits, hex letters, dots
    and colons is dropped as well, because a fragment such as ``140.1.0`` (the start of
    ``140.1.0.15``) matches no address pattern and would reach the model unmasked.
    """
    if len(text) <= limit:
        return text, 0
    end = limit
    while end > 0 and text[end - 1] in _ADDRESS_CHARS:
        end -= 1
    return text[:end], len(text) - end


def _structured_json(value: dict | list, redactor: Redactor) -> str:
    text = json.dumps(
        redactor.tokenize_data(value), separators=(",", ":"), ensure_ascii=False, default=str
    )
    head, omitted = cut_text(text, MAX_STRUCTURED_CHARS)
    return f"{head}… ({omitted} more characters)" if omitted else head


def _filtered(policy: SharingPolicy, path: str, raw: dict | list) -> dict | list:
    if path == "nautobot" and isinstance(raw, dict):
        kept, withheld = filter_nautobot_attributes(policy, raw)
        return {**mask_by_key(policy, kept), **({"withheld": withheld} if withheld else {})}
    return mask_by_key(policy, raw)


def render_prompt(
    template: str,
    context: WorkflowContext,
    redactor: Redactor,
    policy: SharingPolicy,
) -> str | None:
    """Render ``template`` against the first device; ``None`` when a device is needed but absent.

    Raises ``PromptWithheldError`` when a placeholder names data the policy withholds.
    """
    aggregated = apply_run_placeholders(template, context)
    if "{" not in aggregated:
        return finish_run_placeholders(aggregated, context)
    if not context.devices:
        return None
    device = next(iter(context.devices.values()))

    def replace(match: re.Match[str]) -> str:
        path = match.group(1)
        check_path(policy, path)
        raw = resolve_device_attribute_raw(device, path)
        if isinstance(raw, dict | list):
            if not raw:
                return ""
            return _structured_json(_filtered(policy, path, raw), redactor)
        # Scalars keep the shared rule: sealed secrets are never revealed. NUL delimits the
        # run-level markers, so a value must not carry one in.
        value = resolve_device_attribute(device, path, reveal_secrets=False) or ""
        return value.replace("\x00", "")

    return finish_run_placeholders(_PLACEHOLDER.sub(replace, aggregated), context)
