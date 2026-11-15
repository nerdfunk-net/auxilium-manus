"""Parse the step configuration and build the request sent to the agent."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from services.agents.client import HANDLER_NAME_PATTERN
from services.workflow_context.secret_fields import is_sealed_secret, is_secret_key_name
from workflow_steps.common.step_flags import parse_int_flag
from workflow_steps.get_from_agent.config import get_config

STEP_ID = "get-from-agent"

ATTRIBUTE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
RUN_INPUT_REFERENCE = re.compile(r"^\{run_input\.([A-Za-z_][A-Za-z0-9_-]{0,63})\}$")
RUN_INPUT_MARKER = "{run_input."
MAX_ATTRIBUTES = 64
MAX_VALUE_CHARS = 4096
TIMEOUT_RANGE = (1, 600)


@dataclass(frozen=True)
class Attribute:
    name: str
    value: str


@dataclass(frozen=True)
class StepConfig:
    agent_source_id: str
    handler: str
    attributes: tuple[Attribute, ...]
    timeout_seconds: int


def _attributes(config: dict[str, Any]) -> tuple[Attribute, ...]:
    raw = config.get("attributes")
    if raw is None:
        raw = []
    if not isinstance(raw, list) or len(raw) > MAX_ATTRIBUTES:
        raise ValueError(f"{STEP_ID}: attributes must be a list of at most {MAX_ATTRIBUTES} rows")
    rows: list[Attribute] = []
    for index, entry in enumerate(raw, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"{STEP_ID}: attribute row {index} must be an object")
        name = str(entry.get("name") or "").strip()
        value = entry.get("value")
        value_text = "" if value is None else str(value)
        if not name and not value_text.strip():
            continue  # an untouched row in the editor
        if not ATTRIBUTE_NAME_PATTERN.fullmatch(name):
            raise ValueError(
                f"{STEP_ID}: attribute name {name!r} (row {index}) must be a plain name "
                "(letters, digits, '_', '-')"
            )
        if is_secret_key_name(name):
            raise ValueError(
                f"{STEP_ID}: attribute {name!r} looks like a secret; secrets are never sent "
                "to an agent"
            )
        if len(value_text) > MAX_VALUE_CHARS:
            raise ValueError(f"{STEP_ID}: value of {name!r} is longer than {MAX_VALUE_CHARS}")
        rows.append(Attribute(name=name, value=value_text))
    names = [row.name for row in rows]
    if len(set(names)) != len(names):
        raise ValueError(f"{STEP_ID}: attribute names must be unique")
    return tuple(rows)


def parse_config(config: dict[str, Any]) -> StepConfig:
    source_id = str(config.get("agent_source_id") or "").strip()
    if not source_id:
        raise ValueError(f"{STEP_ID}: agent_source_id is not configured")
    handler = str(config.get("handler") or "").strip()
    if not handler:
        raise ValueError(f"{STEP_ID}: handler is required")
    if not HANDLER_NAME_PATTERN.fullmatch(handler):
        raise ValueError(f"{STEP_ID}: handler {handler!r} is not a valid handler name")
    return StepConfig(
        agent_source_id=source_id,
        handler=handler,
        attributes=_attributes(config),
        timeout_seconds=parse_int_flag(
            config,
            "timeout_seconds",
            default=get_config()["timeout_seconds"],
            minimum=TIMEOUT_RANGE[0],
            maximum=TIMEOUT_RANGE[1],
        ),
    )


def build_inputs(config: StepConfig, run_inputs: dict[str, Any] | None) -> dict[str, Any]:
    """``{"attributes": {name: value}, "content": {}}``; run-input references are resolved.

    A reference to a missing run input or to a sealed (secret) one is a ``ValueError``: the
    value would otherwise leave the app or silently become empty.
    """
    inputs = run_inputs or {}
    attributes: dict[str, Any] = {}
    for attribute in config.attributes:
        match = RUN_INPUT_REFERENCE.fullmatch(attribute.value.strip())
        if match is None:
            if RUN_INPUT_MARKER in attribute.value:
                raise ValueError(
                    f"{STEP_ID}: attribute {attribute.name!r} holds a run input reference that "
                    "is not a whole value of the form {run_input.<name>}"
                )
            attributes[attribute.name] = attribute.value
            continue
        key = match.group(1)
        if key not in inputs:
            raise ValueError(
                f"{STEP_ID}: attribute {attribute.name!r} refers to run input {key!r}, "
                "which is not present in this run"
            )
        value = inputs[key]
        if is_sealed_secret(value):
            raise ValueError(
                f"{STEP_ID}: run input {key!r} is a secret and cannot be sent to an agent"
            )
        if isinstance(value, dict | list) or value is None:
            raise ValueError(f"{STEP_ID}: run input {key!r} must be a plain value")
        attributes[attribute.name] = value
    return {"attributes": attributes, "content": {}}
