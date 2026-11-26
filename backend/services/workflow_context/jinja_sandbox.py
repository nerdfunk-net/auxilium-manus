"""The Jinja sandbox of the workflow steps, as plain data in and out (S4-07).

``core/jinja_worker.py`` loads this file by path in a child process started with ``python -I``,
so it may import only Jinja2 and the standard library. ``workflow_steps/common/jinja_render.py``
turns a problem dict back into a ``JinjaTemplateError`` with its ``FailureInfo``.

A problem is ``{"ok": False, "kind", "exception_type", "line", "message"}`` with ``kind`` one of
``template_syntax``, ``undefined_variable``, ``template_error``, ``unsafe_template_value`` or
``too_large``.
"""

from __future__ import annotations

from typing import Any

from jinja2 import TemplateSyntaxError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment

JINJA_ENV = SandboxedEnvironment(
    autoescape=False,
    trim_blocks=True,
    lstrip_blocks=True,
)

UNSAFE_VALUE_MESSAGE = (
    "A value rendered into the template contains a line break; enable "
    "'Allow values with line breaks' on the step if this is intended"
)

# Every character ``str.splitlines()`` treats as a line boundary; a value holding one could be
# split into extra commands by any consumer that uses it.
_LINE_SEPARATORS = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e\x85  ")


class _UnsafeValue(Exception):  # noqa: N818 - internal signal of the finalize hook
    """A value rendered into the template contains a line break (S4-08)."""


def _reject_line_breaks(value: Any) -> Any:
    """Jinja ``finalize`` hook: runs on every ``{{ expression }}`` result, never on template text.

    A data value with a CR/LF would become extra device commands once rendered into a CLI
    template, so it is refused unless the step explicitly allows multi-line values."""
    if isinstance(value, str) and not _LINE_SEPARATORS.isdisjoint(value):
        raise _UnsafeValue
    return value


# Same sandbox, plus the line-break check. The default for rendering that ends up on a device CLI.
_JINJA_ENV_STRICT = JINJA_ENV.overlay(finalize=_reject_line_breaks)


def leading_lines_stripped(template: str) -> int:
    leading = template[: len(template) - len(template.lstrip())]
    return leading.count("\n")


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


def _problem(kind: str, exc_type: str, line: int | None, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "kind": kind,
        "exception_type": exc_type,
        "line": line,
        "message": message,
    }


def empty_problem() -> dict[str, Any]:
    return _problem("template_syntax", "ValueError", None, "Template is empty")


def syntax_problem(template: str, exc: TemplateSyntaxError) -> dict[str, Any]:
    line = exc.lineno + leading_lines_stripped(template) if exc.lineno else None
    return _problem("template_syntax", type(exc).__name__, line, f"Jinja syntax error: {exc}")


def render_plain(
    template: str,
    context: dict[str, Any],
    *,
    allow_multiline_values: bool,
    max_output_chars: int | None = None,
) -> dict[str, Any]:
    """``{"ok": True, "output"}`` or a problem dict. Never raises for a template problem.

    By default a ``{{ value }}`` containing a line break is refused (S4-08): external data is
    untrusted input to device command lines."""
    stripped = template.strip()
    if not stripped:
        return empty_problem()
    offset = leading_lines_stripped(template)
    env = JINJA_ENV if allow_multiline_values else _JINJA_ENV_STRICT
    try:
        # One parse: ``from_string`` raises the same syntax errors the validator reports.
        output = env.from_string(stripped).render(**context)
    except _UnsafeValue as exc:
        line = _render_line(exc, offset=offset)
        return _problem(
            "unsafe_template_value", "UnsafeTemplateValueError", line, UNSAFE_VALUE_MESSAGE
        )
    except TemplateSyntaxError as exc:
        return syntax_problem(template, exc)
    except UndefinedError as exc:
        line = _render_line(exc, offset=offset)
        message = f"Undefined template variable: {exc}"
        return _problem("undefined_variable", type(exc).__name__, line, message)
    except Exception as exc:
        line = _render_line(exc, offset=offset)
        message = f"Template render failed: {exc}"
        return _problem("template_error", type(exc).__name__, line, message)
    if max_output_chars is not None and len(output) > max_output_chars:
        return _problem("too_large", "", None, "")
    return {"ok": True, "output": output}
