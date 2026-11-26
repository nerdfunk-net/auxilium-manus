"""Hygiene leftovers of the workflow steps (W2-15, W5-13 item 5 / W1-08, W12 row 41)."""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

STEPS = Path(__file__).resolve().parents[2] / "workflow_steps"


def test_no_step_module_declares_its_own_nautobot_concurrency() -> None:
    """One ``NAUTOBOT_CONCURRENCY`` in ``common/nautobot_step.py``; seven ``_CONCURRENCY = 5``
    copies before."""
    found = []
    for path in sorted(STEPS.rglob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "_CONCURRENCY" for t in node.targets
            ):
                found.append(str(path.relative_to(STEPS)))
    assert found == []


def test_the_shared_nautobot_concurrency_keeps_its_value() -> None:
    from workflow_steps.common.nautobot_step import NAUTOBOT_CONCURRENCY

    assert NAUTOBOT_CONCURRENCY == 5


@pytest.mark.parametrize(
    ("module", "name"),
    [
        ("workflow_steps.common.batfish_properties", "is_empty_value"),
        ("workflow_steps.common.batfish_properties", "row_matches_empty"),
        ("workflow_steps.common.batfish_context", "resolve_batfish_snapshot"),
        ("services.ise.lookup", "ip_entry_matches"),
    ],
)
def test_helpers_used_only_inside_their_module_are_private(module: str, name: str) -> None:
    mod = importlib.import_module(module)

    assert not hasattr(mod, name)
    assert hasattr(mod, f"_{name}")
    assert name not in getattr(mod, "__all__", ())


def test_the_crawler_knows_a_seed_by_its_seed_id_only() -> None:
    source = (STEPS / "discover_network" / "crawler.py").read_text()

    assert "target.depth == 0" not in source
