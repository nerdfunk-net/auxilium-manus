"""Jinja2 validation and rendering for workflow templates."""

from __future__ import annotations

from typing import Any

from jinja2 import TemplateSyntaxError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment

from models.workflow_context import DeviceContext
from services.workflow_context.secret_fields import is_sealed_secret, unwrap_secret

_jinja_env = SandboxedEnvironment(
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)


class JinjaTemplateError(ValueError):
    """Raised when a template is invalid or cannot be rendered."""


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
        raise JinjaTemplateError("Template is empty")
    try:
        _jinja_env.parse(stripped)
    except TemplateSyntaxError as exc:
        raise JinjaTemplateError(f"Jinja syntax error: {exc}") from exc


def render_jinja_template(template: str, context: dict[str, Any]) -> str:
    """Render a template against a namespace context."""
    validate_jinja_template(template)
    try:
        compiled = _jinja_env.from_string(template.strip())
        rendered = compiled.render(**context)
    except UndefinedError as exc:
        raise JinjaTemplateError(f"Undefined template variable: {exc}") from exc
    except Exception as exc:
        raise JinjaTemplateError(f"Template render failed: {exc}") from exc
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
