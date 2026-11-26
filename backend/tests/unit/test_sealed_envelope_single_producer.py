"""Guard 5 (W11-11): every sealed secret is registered for run-scoped redaction.

``secret_fields.seal_secret`` registers the cleartext before it builds the envelope
(``SealRegistersCleartextTests``). That holds for every producer only while ``seal_secret`` is
the one place that builds an envelope: production code outside ``secret_fields.py`` may not name
``SEALED_MARKER`` or spell its value. Callers test for an envelope with ``is_sealed_secret`` and
make one with ``seal_secret``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from services.workflow_context.secret_fields import SEALED_MARKER

BACKEND = Path(__file__).resolve().parents[2]
HOME = "services/workflow_context/secret_fields.py"
_SKIPPED_DIRS = {"tests", ".venv", "__pycache__"}


def sites_in(source: str) -> list[int]:
    """Lines that name ``SEALED_MARKER`` or spell its value."""
    lines: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and any(a.name == "SEALED_MARKER" for a in node.names):
            lines.append(node.lineno)
        elif isinstance(node, ast.Name) and node.id == "SEALED_MARKER":
            lines.append(node.lineno)
        elif isinstance(node, ast.Attribute) and node.attr == "SEALED_MARKER":
            lines.append(node.lineno)
        elif isinstance(node, ast.Constant) and node.value == SEALED_MARKER:
            lines.append(node.lineno)
    return lines


def _production_files() -> list[Path]:
    return [
        path
        for path in sorted(BACKEND.rglob("*.py"))
        if not _SKIPPED_DIRS.intersection(path.relative_to(BACKEND).parts)
    ]


def test_only_seal_secret_builds_an_envelope() -> None:
    offenders = {
        rel: lines
        for path in _production_files()
        if (rel := path.relative_to(BACKEND).as_posix()) != HOME
        and (lines := sites_in(path.read_text()))
    }
    assert offenders == {}, (
        "build an envelope with seal_secret() and test for one with is_sealed_secret(); "
        f"a hand-made envelope skips the redaction registry: {offenders}"
    )


def test_the_home_module_is_where_the_marker_lives() -> None:
    assert sites_in((BACKEND / HOME).read_text())


@pytest.mark.parametrize(
    "source",
    [
        "from services.workflow_context.secret_fields import SEALED_MARKER",
        "x = {SEALED_MARKER: True}",
        "x = secret_fields.SEALED_MARKER",
        f'x = {{"{SEALED_MARKER}": True, "ct": token}}',
        f'ok = value.get("{SEALED_MARKER}") is True',
    ],
)
def test_the_rule_finds_a_hand_made_envelope(source: str) -> None:
    assert sites_in(source) == [1]


@pytest.mark.parametrize(
    "source",
    [
        "x = seal_secret(value)",
        "ok = is_sealed_secret(value)",
        'x = {"__sealed__": True}',
    ],
)
def test_the_rule_leaves_the_api_alone(source: str) -> None:
    assert sites_in(source) == []
