"""Parse the step configuration and build the per-device request for the agent."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from models.workflow_context import DeviceContext
from services.agents.client import HANDLER_NAME_PATTERN
from services.workflow_context.attribute_path import (
    DEVICE_SCALAR_FIELDS,
    resolve_device_attribute_raw,
)
from services.workflow_context.secret_fields import (
    SECRET_BAG_PATHS,
    SECRET_BAG_SUBTREES,
    contains_sealed_secret,
    is_secret_key_name,
)
from workflow_steps.common.attribute_write import set_device_attribute
from workflow_steps.common.content_resolver import list_exportable_content
from workflow_steps.common.step_flags import parse_bool_flag, parse_int_flag
from workflow_steps.route_to_agent.config import get_config

STEP_ID = "route-to-agent"

OUTPUT_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
STATIC_CONTENT_INPUTS = ("running_config", "startup_config", "latest_command_output")
COMMAND_OUTPUT_PREFIX = "command_output:"
MAX_PARAMS_BYTES = 16 * 1024
MAX_LIST_ITEMS = 64
TIMEOUT_RANGE = (1, 600)
# "device" is the core device fields, "error" a read-only namespace; parsed/run_input are
# refused by set_device_attribute itself.
RESERVED_ROOTS = frozenset({"device", "error", "parsed", "run_input"})

# A throw-away device used to run the destination path through the same rules that
# set_device_attribute applies at write time, so a bad path fails the step up front.
_PROBE = DeviceContext(id="probe", name="probe", hostname="probe")


_PATH_BRACKETS = re.compile(r"\[[^\]]*\]")


class InputRefusedError(Exception):
    """A selected input must not leave the app through this step; ``code`` names why."""

    code = "source_refused"

    def __init__(self, path: str, message: str) -> None:
        super().__init__(message)
        self.path = path


class InputSealedError(InputRefusedError):
    """A selected input holds a sealed secret."""

    code = "source_sealed"

    def __init__(self, path: str) -> None:
        super().__init__(
            path, f"input {path!r} holds a sealed secret and cannot be sent to an agent"
        )


class InputSecretError(InputRefusedError):
    """A selected structure holds a value under a secret-looking key (``password``, ...)."""

    code = "source_secret"

    def __init__(self, path: str, key: str) -> None:
        super().__init__(
            path, f"input {path!r} contains a value under the secret-looking key {key!r}"
        )


@dataclass(frozen=True)
class StepConfig:
    agent_source_id: str
    handler: str
    params: dict[str, Any]
    input_paths: tuple[str, ...]
    content_inputs: tuple[str, ...]
    destination_path: str
    output_keys: tuple[str, ...]
    allow_missing_outputs: bool
    timeout_seconds: int


def _string_list(config: dict[str, Any], key: str) -> tuple[str, ...]:
    raw = config.get(key, get_config()[key])
    if raw is None:
        raw = []
    if not isinstance(raw, list) or len(raw) > MAX_LIST_ITEMS:
        raise ValueError(f"{STEP_ID}: {key} must be a list of at most {MAX_LIST_ITEMS} entries")
    items: list[str] = []
    for entry in raw:
        if not isinstance(entry, str) or not entry.strip():
            raise ValueError(f"{STEP_ID}: {key} entries must be non-empty strings")
        items.append(entry.strip())
    if len(set(items)) != len(items):
        raise ValueError(f"{STEP_ID}: {key} must not contain duplicates")
    return tuple(items)


def _content_input(entry: str) -> str:
    if entry in STATIC_CONTENT_INPUTS:
        return entry
    if entry.startswith(COMMAND_OUTPUT_PREFIX) and entry[len(COMMAND_OUTPUT_PREFIX) :].strip():
        return entry
    raise ValueError(
        f"{STEP_ID}: unknown content input {entry!r}; use one of "
        f"{', '.join(STATIC_CONTENT_INPUTS)} or {COMMAND_OUTPUT_PREFIX}<node_id>"
    )


def _params(config: dict[str, Any]) -> dict[str, Any]:
    raw = config.get("params")
    params = {} if raw is None else raw
    if not isinstance(params, dict):
        raise ValueError(f"{STEP_ID}: params must be a JSON object")
    try:
        encoded = json.dumps(params, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{STEP_ID}: params must be JSON serialisable") from exc
    if len(encoded.encode("utf-8")) > MAX_PARAMS_BYTES:
        raise ValueError(f"{STEP_ID}: params must be at most {MAX_PARAMS_BYTES} bytes")
    return params


def _destination(config: dict[str, Any]) -> str:
    destination = str(config.get("destination_path") or "").strip()
    if not destination:
        raise ValueError(f"{STEP_ID}: destination_path is required")
    segments = destination.split(".")
    if any(not OUTPUT_KEY_PATTERN.fullmatch(segment) for segment in segments):
        raise ValueError(f"{STEP_ID}: destination_path segments must be plain names")
    root = segments[0]
    # The agent enriches; it must never be able to rewrite the device itself. (set_device_attribute
    # accepts "device.name" and bare scalar names for other steps, so they are refused here.)
    if root in RESERVED_ROOTS or root in DEVICE_SCALAR_FIELDS:
        raise ValueError(
            f"{STEP_ID}: destination_path {destination!r} may not start with {root!r}; "
            "write to an attribute bag such as agent.<id>"
        )
    try:
        set_device_attribute(_PROBE, destination, {})
    except ValueError as exc:
        raise ValueError(f"{STEP_ID}: destination_path {destination!r}: {exc}") from exc
    return destination


def secret_path_problem(path: str) -> str | None:
    """Why *path* must not be sent to an agent, or ``None``.

    The same rules the other sinks apply (``store-for-report``, persisted results, the AI copy):
    known secret leaves and the config-context documents, reached directly, from below, or by
    selecting a parent that would carry them along (``nautobot`` is the whole bag), plus any path
    segment that names a secret (``password``, ``*_token``, ...).
    """
    segments = tuple(_PATH_BRACKETS.sub("", part) for part in path.split(".") if part)
    for secret in (*SECRET_BAG_PATHS, *SECRET_BAG_SUBTREES):
        shared = min(len(secret), len(segments))
        if shared and segments[:shared] == secret[:shared]:
            return f"{path!r} is, contains or lies within secret data ({'.'.join(secret)})"
    for segment in segments:
        if is_secret_key_name(segment):
            return f"{path!r} has the secret-looking segment {segment!r}"
    return None


def _checked_input_paths(config: dict[str, Any]) -> tuple[str, ...]:
    paths = _string_list(config, "input_paths")
    for path in paths:
        problem = secret_path_problem(path)
        if problem:
            raise ValueError(
                f"{STEP_ID}: secrets are never sent to an agent: {problem}. Select the specific "
                "non-secret values instead."
            )
    return paths


def _find_secret_key(value: Any) -> str | None:
    """The first secret-looking dict key with a non-empty value anywhere inside *value*."""
    stack: list[Any] = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, child in current.items():
                if isinstance(key, str) and is_secret_key_name(key) and child:
                    return key
                stack.append(child)
        elif isinstance(current, list):
            stack.extend(current)
    return None


def parse_config(config: dict[str, Any]) -> StepConfig:
    handler = str(config.get("handler") or "").strip()
    if not handler:
        raise ValueError(f"{STEP_ID}: handler is required")
    if not HANDLER_NAME_PATTERN.fullmatch(handler):
        raise ValueError(f"{STEP_ID}: handler {handler!r} is not a valid handler name")

    output_keys = _string_list(config, "output_keys")
    if not output_keys:
        raise ValueError(f"{STEP_ID}: output_keys must name at least one key the agent returns")
    for key in output_keys:
        if not OUTPUT_KEY_PATTERN.fullmatch(key):
            raise ValueError(f"{STEP_ID}: output key {key!r} must be a plain name (no dots)")

    input_paths = _checked_input_paths(config)
    content_inputs = tuple(
        _content_input(entry) for entry in _string_list(config, "content_inputs")
    )
    if not input_paths and not content_inputs:
        raise ValueError(f"{STEP_ID}: select at least one input to send (input_paths or content)")

    source_id = str(config.get("agent_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{STEP_ID}: agent_source_id is not configured")

    return StepConfig(
        agent_source_id=source_id,
        handler=handler,
        params=_params(config),
        input_paths=input_paths,
        content_inputs=content_inputs,
        destination_path=_destination(config),
        output_keys=output_keys,
        allow_missing_outputs=parse_bool_flag(config, "allow_missing_outputs", default=False),
        timeout_seconds=parse_int_flag(
            config,
            "timeout_seconds",
            default=get_config()["timeout_seconds"],
            minimum=TIMEOUT_RANGE[0],
            maximum=TIMEOUT_RANGE[1],
        ),
    )


async def build_inputs(
    device: DeviceContext, config: StepConfig, artifact_service: Any
) -> dict[str, Any]:
    """``{"attributes": {path: value}, "content": {name: text}}`` for one device.

    Paths and content that do not exist on the device are left out; the handler sees what is
    there. A sealed secret anywhere in a selected value raises ``InputSealedError``.
    """
    attributes: dict[str, Any] = {}
    for path in config.input_paths:
        value = resolve_device_attribute_raw(device, path)
        if value is None:
            continue
        if contains_sealed_secret(value):
            raise InputSealedError(path)
        secret_key = _find_secret_key(value)
        if secret_key is not None:
            raise InputSecretError(path, secret_key)
        attributes[path] = value

    content: dict[str, Any] = {}
    for name in config.content_inputs:
        resolved = await _read_content(device, name, artifact_service)
        if resolved is not None:
            content[name] = resolved
    return {"attributes": attributes, "content": content}


async def _read_content(device: DeviceContext, name: str, artifact_service: Any) -> Any | None:
    if name.startswith(COMMAND_OUTPUT_PREFIX):
        node_id = name[len(COMMAND_OUTPUT_PREFIX) :].strip()
        items = list_exportable_content(
            device, content_source="command_output", source_step_node_id=node_id
        )
        # A list, not a dict keyed by command text: the same command can run twice and both
        # outputs must reach the handler.
        outputs = [
            {
                "command": str(item.extra.get("command") or ""),
                "output": await artifact_service.resolve(item.artifact_ref),
            }
            for item in items
        ]
        return outputs or None
    items = list_exportable_content(device, content_source=name)
    if not items:
        return None
    return await artifact_service.resolve(items[0].artifact_ref)
