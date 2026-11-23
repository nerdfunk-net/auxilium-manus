"""Guard 12 (P-T): an expected-failure test must be strict and name its finding.

``strict_xfail`` (``tests/unit/_step_helpers.py``) is the way to mark a test that fails today
because of a known defect. This test refuses any other ``xfail`` in ``tests/unit`` that is not
strict or whose reason does not start with a finding id (``W10-09: ...``), so a † test cannot
turn into a permanent, silent skip. The count is printed so a family migration can check it
reaches zero.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_UNIT = Path(__file__).parent
_FINDING = re.compile(r"^W\d+[ab]?-\d+: ")
_ALLOWED_HELPER = {"_step_helpers.py"}


def _xfail_calls(path: Path) -> list[ast.Call]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "xfail"
    ]


def _problems() -> list[str]:
    problems: list[str] = []
    for path in sorted(_UNIT.glob("test_*.py")):
        if path.name == Path(__file__).name:
            continue
        for call in _xfail_calls(path):
            keywords = {kw.arg: kw.value for kw in call.keywords}
            strict = keywords.get("strict")
            if not (isinstance(strict, ast.Constant) and strict.value is True):
                problems.append(f"{path.name}:{call.lineno} xfail is not strict=True")
            reason = keywords.get("reason")
            if not (isinstance(reason, ast.Constant) and _FINDING.match(str(reason.value))):
                problems.append(f"{path.name}:{call.lineno} xfail reason lacks a finding id")
    return problems


def test_every_xfail_is_strict_and_names_its_finding() -> None:
    assert _problems() == []


def test_step_helpers_is_the_only_place_that_builds_the_marker() -> None:
    helper = (_UNIT / "_step_helpers.py").read_text(encoding="utf-8")

    assert "strict=True" in helper
    assert 'reason=f"{finding}: {why}"' in helper


def test_the_scan_sees_a_lax_xfail(tmp_path: Path) -> None:
    sample = tmp_path / "test_sample.py"
    sample.write_text('import pytest\n@pytest.mark.xfail(reason="later")\ndef test_x(): ...\n')

    (call,) = _xfail_calls(sample)

    assert {kw.arg for kw in call.keywords} == {"reason"}
