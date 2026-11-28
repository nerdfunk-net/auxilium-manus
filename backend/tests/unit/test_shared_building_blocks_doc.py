"""Guard 13: "Shared building blocks" (doc/WORKFLOW-STEPS.md) lists every ``common/`` module.

The table is what an author (or the AI) reads before writing a helper, so it must not go stale:
every module in ``backend/workflow_steps/common/`` appears in it as ``common/<module>.py``, and
every module it names exists. Adding a module to ``common/`` means adding a row (task, module,
entry points); deleting or renaming one means fixing the row.
"""

from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
COMMON = BACKEND / "workflow_steps" / "common"
DOC = BACKEND.parent / "doc" / "WORKFLOW-STEPS.md"

START_MARKER = "<!-- shared-building-blocks:start -->"
END_MARKER = "<!-- shared-building-blocks:end -->"
MODULE_REFERENCE = re.compile(r"`common/([a-z0-9_]+)\.py`")


def _common_modules() -> set[str]:
    return {path.stem for path in COMMON.glob("*.py") if path.name != "__init__.py"}


def _documented_modules() -> set[str]:
    text = DOC.read_text(encoding="utf-8")
    assert START_MARKER in text and END_MARKER in text, (
        f"{DOC.name} has no '{START_MARKER}' ... '{END_MARKER}' block"
    )
    block = text.split(START_MARKER, 1)[1].split(END_MARKER, 1)[0]
    return set(MODULE_REFERENCE.findall(block))


def test_every_common_module_is_in_the_table() -> None:
    missing = sorted(_common_modules() - _documented_modules())
    assert not missing, (
        "workflow_steps/common modules missing from 'Shared building blocks' in "
        f"doc/WORKFLOW-STEPS.md (add a row naming `common/<module>.py`): {missing}"
    )


def test_the_table_names_no_missing_module() -> None:
    stale = sorted(_documented_modules() - _common_modules())
    assert not stale, (
        "'Shared building blocks' in doc/WORKFLOW-STEPS.md names modules that no longer "
        f"exist in workflow_steps/common: {stale}"
    )
