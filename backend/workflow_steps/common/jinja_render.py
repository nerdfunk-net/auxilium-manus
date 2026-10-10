"""Jinja2 validation and rendering for workflow templates."""

from __future__ import annotations

from typing import Any

from jinja2 import TemplateSyntaxError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment

from models.failure import FailureInfo, FailureKind
from models.workflow_context import DeviceContext
from services.workflow_context.secret_fields import is_sealed_secret, unwrap_secret

_jinja_env = SandboxedEnvironment(
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


class JinjaTemplateError(ValueError):
    """Raised when a template is invalid or cannot be rendered.

    ``failure`` says which kind of problem and on which line, without any text of the message
    (see ``models.failure``).
    """

    def __init__(self, message: str, *, failure: FailureInfo | None = None) -> None:
        super().__init__(message)
        self.failure = failure


def _template_failure(kind: FailureKind, exc: BaseException, *, line: int | None) -> FailureInfo:
    return FailureInfo(
        phase="render",
        kind=kind,
        exception_type=type(exc).__name__,
        hint="fix_template",
        line=line,
    )


def _render_line(exc: BaseException, *, offset: int) -> int | None:
    """Template line (as the author sees it) where *exc* was raised, from its traceback.

    Jinja compiles templates under the file name ``<template>`` and maps the frame's line number
    to the template line. ``offset`` is the number of leading lines ``render`` stripped.
    """
    line: int | None = None
    tb = exc.__traceback__
    while tb is not None:
        if tb.tb_frame.f_code.co_filename == "<template>":
            line = tb.tb_lineno
        tb = tb.tb_next
    return line + offset if line is not None else None


def _leading_lines_stripped(template: str) -> int:
    leading = template[: len(template) - len(template.lstrip())]
    return leading.count("\n")


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
        raise JinjaTemplateError(
            "Template is empty",
            failure=_template_failure("template_syntax", ValueError(), line=None),
        )
    try:
        _jinja_env.parse(stripped)
    except TemplateSyntaxError as exc:
        line = exc.lineno + _leading_lines_stripped(template) if exc.lineno else None
        raise JinjaTemplateError(
            f"Jinja syntax error: {exc}",
            failure=_template_failure("template_syntax", exc, line=line),
        ) from exc


def render_jinja_template(template: str, context: dict[str, Any]) -> str:
    """Render a template against a namespace context."""
    validate_jinja_template(template)
    try:
        compiled = _jinja_env.from_string(template.strip())
        rendered = compiled.render(**context)
    except UndefinedError as exc:
        raise JinjaTemplateError(
            f"Undefined template variable: {exc}",
            failure=_template_failure(
                "undefined_variable",
                exc,
                line=_render_line(exc, offset=_leading_lines_stripped(template)),
            ),
        ) from exc
    except Exception as exc:
        raise JinjaTemplateError(
            f"Template render failed: {exc}",
            failure=_template_failure(
                "template_error",
                exc,
                line=_render_line(exc, offset=_leading_lines_stripped(template)),
            ),
        ) from exc
    return rendered


def parse_output_key(raw: Any) -> str:
    key = str(raw or "").strip()
    if not key:
        raise JinjaTemplateError("output_key is required")
    if not key.replace("_", "").isalnum() or not key[0].isalpha():
        raise JinjaTemplateError(
            "output_key must start with a letter and contain only letters, numbers, or underscores"
        )
    return key
