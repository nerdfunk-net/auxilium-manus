"""Jinja2 syntax check and lenient trial render for the AI assistant's template tools.

Same sandbox knobs as services/templates/templates_service.py (so the model cannot exercise
anything the editor's own preview could not). The difference is *lenient* undefined handling:
the template editor's device/run variables are withheld from the model, so references to them
must not fail the render. They render as ``<<name>>`` and are reported, which lets the model
check syntax and logic without ever seeing device data.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from jinja2 import ChainableUndefined, TemplateError, TemplateSyntaxError
from jinja2.exceptions import SecurityError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment

# Results of ``*`` and ``**`` the trial render will build. The stock sandbox only bounds ``range``,
# so ``{{ 'a' * 10**9 }}`` would otherwise allocate gigabytes.
MAX_REPEAT_LENGTH = 1_000_000
MAX_POWER_BITS = 100_000


class _BoundedSandbox(SandboxedEnvironment):
    intercepted_binops = frozenset({"*", "**"})

    def call_binop(self, context: Any, operator: str, left: Any, right: Any) -> Any:
        if operator == "*":
            for sequence, count in ((left, right), (right, left)):
                if (
                    isinstance(sequence, str | bytes | list | tuple)
                    and isinstance(count, int)
                    and len(sequence) * max(count, 0) > MAX_REPEAT_LENGTH
                ):
                    raise SecurityError("repeating a sequence this often is not allowed")
        elif (
            isinstance(left, int)
            and isinstance(right, int)
            and right > 0
            and abs(left) > 1
            and right * abs(left).bit_length() > MAX_POWER_BITS
        ):
            raise SecurityError("this power is too large to compute")
        return super().call_binop(context, operator, left, right)


@dataclass(frozen=True)
class SyntaxProblem:
    message: str
    line: int | None


@dataclass(frozen=True)
class RenderOutcome:
    ok: bool
    output: str = ""
    error: str | None = None
    error_line: int | None = None
    withheld: tuple[str, ...] = ()


def _syntax_env() -> SandboxedEnvironment:
    return SandboxedEnvironment(autoescape=False, trim_blocks=True, lstrip_blocks=True)


def check_syntax(content: str) -> SyntaxProblem | None:
    """Parse *and compile* (compilation catches e.g. unknown filters). None means valid."""
    try:
        _syntax_env().from_string(content)
    except TemplateSyntaxError as exc:
        return SyntaxProblem(message=exc.message or "syntax error", line=exc.lineno)
    except TemplateError as exc:
        return SyntaxProblem(message=str(exc), line=None)
    return None


def _parse_value(value: str) -> Any:
    if value == "":
        return ""
    try:
        return json.loads(value)
    except ValueError:
        return value


def build_context(
    variables: Iterable[Any], samples: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Nested render context from the editor's *custom* variables, plus model-supplied samples.

    Mirrors the frontend's ``buildVariablesContext``: dotted names nest, values are parsed as
    JSON when they are valid JSON. Auto-filled (device/run) variables are skipped on purpose.
    """
    context: dict[str, Any] = {}
    for variable in variables:
        if variable.is_auto or not variable.name:
            continue
        parts = variable.name.split(".")
        node = context
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        node[parts[-1]] = _parse_value(variable.value)
    if samples:
        context.update(samples)
    return context


def render_lenient(content: str, context: Mapping[str, Any]) -> RenderOutcome:
    withheld: list[str] = []

    class _Placeholder(ChainableUndefined):
        __slots__ = ()

        def __str__(self) -> str:
            name = self._undefined_name or "?"
            if name not in withheld:
                withheld.append(name)
            return f"<<{name}>>"

    env = _BoundedSandbox(
        autoescape=False, trim_blocks=True, lstrip_blocks=True, undefined=_Placeholder
    )
    try:
        output = env.from_string(content).render(**context)
    except TemplateSyntaxError as exc:
        return RenderOutcome(ok=False, error=exc.message or "syntax error", error_line=exc.lineno)
    except UndefinedError as exc:
        return RenderOutcome(
            ok=False,
            error=f"{exc} (this may only be caused by a withheld device/run variable)",
            withheld=tuple(withheld),
        )
    except SecurityError as exc:
        return RenderOutcome(ok=False, error=f"disallowed construct: {exc}")
    except (TemplateError, ArithmeticError, TypeError, ValueError) as exc:
        return RenderOutcome(ok=False, error=f"render failed: {exc}", withheld=tuple(withheld))
    return RenderOutcome(ok=True, output=output, withheld=tuple(withheld))
