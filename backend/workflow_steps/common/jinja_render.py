"""Jinja2 validation and rendering for workflow templates.

A render runs the author's template in a killable child process (S4-07, ``core/jinja_worker.py``):
an endless loop or a huge output stops that one device after ``STEP_CHILD_SECONDS`` instead of
holding a worker thread for good. Parsing (validation, the variables a template reads) stays in
this process.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from jinja2 import TemplateSyntaxError, meta

from core import isolated_process
from models.failure import FailureInfo, FailureKind
from models.workflow_context import DeviceContext
from services.workflow_context.jinja_sandbox import (
    JINJA_ENV,
    empty_problem,
    syntax_problem,
)
from services.workflow_context.secret_fields import is_sealed_secret, unwrap_secret
from workflow_steps.common.failure_records import TEMPLATE_STOPPED

logger = logging.getLogger(__name__)

_WORKER = Path(__file__).resolve().parents[2] / "core" / "jinja_worker.py"
# A rendered text above this many characters stops the device (a loop that writes forever).
MAX_RENDERED_CHARS = 8 * 1024 * 1024
# Characters may grow in JSON (escapes); the worker already refused anything above the cap.
_MAX_RESPONSE_BYTES = 6 * MAX_RENDERED_CHARS + 1024 * 1024


class JinjaTemplateError(ValueError):
    """Raised when a template is invalid or cannot be rendered.

    ``failure`` says which kind of problem and on which line, without any text of the message
    (see ``models.failure``).
    """

    def __init__(self, message: str, *, failure: FailureInfo | None = None) -> None:
        super().__init__(message)
        self.failure = failure


class UnsafeTemplateValueError(JinjaTemplateError):
    """A value rendered into the template contains a line break (S4-08)."""


class TemplateStoppedError(JinjaTemplateError):
    """The render used more than its time or memory, or wrote more than ``MAX_RENDERED_CHARS``."""


_PROBLEM_KINDS: frozenset[FailureKind] = frozenset(
    {"template_syntax", "undefined_variable", "template_error", "unsafe_template_value"}
)


def _error_from(problem: dict[str, Any]) -> JinjaTemplateError:
    """The ``JinjaTemplateError`` for a problem dict of ``jinja_sandbox``."""
    kind = problem.get("kind")
    if kind == "too_large":
        return TemplateStoppedError(
            f"The rendered text is larger than {MAX_RENDERED_CHARS} characters",
            failure=TEMPLATE_STOPPED,
        )
    if kind not in _PROBLEM_KINDS:
        return _stopped()
    line = problem.get("line")
    failure = FailureInfo(
        phase="render",
        kind=kind,
        exception_type=str(problem.get("exception_type") or "") or None,
        hint="fix_template",
        line=line if isinstance(line, int) else None,
    )
    message = str(problem.get("message") or "")
    if kind == "unsafe_template_value":
        return UnsafeTemplateValueError(message, failure=failure)
    return JinjaTemplateError(message, failure=failure)


def _stopped() -> TemplateStoppedError:
    return TemplateStoppedError(
        f"The template was stopped: it used more than {isolated_process.STEP_CHILD_SECONDS:g} "
        "seconds or too much memory",
        failure=TEMPLATE_STOPPED,
    )


def _unwrap_value(value: Any) -> Any:
    """Recursively unwrap sealed secret envelopes anywhere in a bag value —
    including inside lists, so a template can loop an array of per-item secrets
    (e.g. ``{% for c in nautobot.config_context.credentials %}{{ c.password }}``)."""
    if is_sealed_secret(value):
        return unwrap_secret(value)
    if isinstance(value, dict):
        return {key: _unwrap_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_unwrap_value(item) for item in value]
    return value


def _unwrap_bag(bag: dict[str, Any]) -> dict[str, Any]:
    """Recursively unwrap sealed secret envelopes so templates can still use
    e.g. ``{{ tacacs.shared_secret }}`` directly — bags stay sealed at rest,
    only the in-memory Jinja namespace built for this render sees cleartext."""
    return {key: _unwrap_value(value) for key, value in bag.items()}


def build_jinja_context(
    device: DeviceContext,
    *,
    run_id: str | None = None,
    workflow_id: str | None = None,
) -> dict[str, Any]:
    """Build the template namespace tree for a device."""
    from services.workflow_context.device_template import build_template_context

    context = build_template_context(device, run_id=run_id)
    context["workflow"] = {"id": workflow_id or ""}
    # build_template_context seeds "nautobot"/"git" from the raw bags without
    # unwrapping — a config-context array of per-item secrets lives there, so
    # unwrap those namespaces too (not just the pass-through bags below).
    for fixed_bag in ("nautobot", "git"):
        if isinstance(context.get(fixed_bag), dict):
            context[fixed_bag] = _unwrap_bag(context[fixed_bag])
    for bag_name, bag_value in device.attribute_bags.items():
        if bag_name not in context:
            context[bag_name] = _unwrap_bag(dict(bag_value))
    if device.parsed:
        context["parsed"] = dict(device.parsed)
    return context


def validate_jinja_template(template: str) -> None:
    """Parse a template and raise JinjaTemplateError on syntax errors."""
    stripped = template.strip()
    if not stripped:
        raise _error_from(empty_problem())
    try:
        JINJA_ENV.parse(stripped)
    except TemplateSyntaxError as exc:
        raise _error_from(syntax_problem(template, exc)) from exc


def template_variables(template: str) -> frozenset[str]:
    """The top-level names a template reads from its context (a syntax error yields none; the
    render reports it)."""
    try:
        return frozenset(meta.find_undeclared_variables(JINJA_ENV.parse(template.strip())))
    except TemplateSyntaxError:
        return frozenset()


async def render_jinja_template(
    template: str, context: dict[str, Any], *, allow_multiline_values: bool = False
) -> str:
    """Render a template against a namespace context, in the isolated worker.

    By default a ``{{ value }}`` containing a line break is rejected (S4-08): external data is
    untrusted input to device command lines. Raises ``JinjaTemplateError`` (with its
    ``FailureInfo``) for every problem, ``TemplateStoppedError`` when the render was stopped."""
    try:
        payload = json.dumps(
            {
                "template": template,
                "context": context,
                "allow_multiline_values": allow_multiline_values,
                "max_output_chars": MAX_RENDERED_CHARS,
            }
        ).encode()
    except (TypeError, ValueError) as exc:  # no default=str: never render a value's repr
        raise JinjaTemplateError(
            "The template context contains a value that is not plain data",
            failure=FailureInfo(
                phase="render",
                kind="template_error",
                exception_type=type(exc).__name__,
                hint="fix_template",
            ),
        ) from exc
    async with isolated_process.STEP_CHILD_SLOTS.hold(wait_seconds=None):
        stdout = await isolated_process.run_child(
            _WORKER,
            payload,
            timeout=isolated_process.STEP_CHILD_SECONDS,
            max_response_bytes=_MAX_RESPONSE_BYTES,
        )
    if stdout is None:
        raise _stopped()
    try:
        result = json.loads(stdout)
        if result["ok"]:
            return str(result["output"])
    except ValueError, KeyError, TypeError:
        logger.warning("The Jinja worker returned an unusable result")
        raise _stopped() from None
    raise _error_from(result)
