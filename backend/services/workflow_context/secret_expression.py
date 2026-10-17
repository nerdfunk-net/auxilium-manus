"""Secret-valued step fields must be references, never literals.

A literal typed into a node's config is stored in ``workflows.canvas_nodes`` and mirrored to the
workflows git repository in clear text. A field that carries a secret therefore has to be a
whole-string ``{path.to.attribute}`` expression resolved per device at run time. A
``| default('…')`` clause is a literal in disguise and is rejected too.
"""

from __future__ import annotations

import re

_SECRET_EXPRESSION = re.compile(r"^\{\s*[^{}|]+?\s*\}$")


def secret_expression_problem(raw_value: str) -> str | None:
    """Return why *raw_value* is not an acceptable secret expression, or ``None``."""
    expression = (raw_value or "").strip()
    if not expression:
        return "is empty"
    if "|" in expression:
        return (
            "must not use a '| default(...)' fallback (the fallback would be stored in clear text)"
        )
    if _SECRET_EXPRESSION.match(expression) is None:
        return "must be a {path.to.attribute} expression, not a literal value"
    return None


def require_secret_expression(raw_value: str, *, field: str, step_id: str) -> str:
    """Return the stripped expression or raise ``ValueError`` (a configuration error)."""
    problem = secret_expression_problem(raw_value)
    if problem is not None:
        raise ValueError(
            f"{step_id}: {field} {problem}. Fill the attribute from Secret Get, Secret Generate "
            "or Generate Password and reference it, e.g. {tacacs.new_key}."
        )
    return raw_value.strip()
