"""S4-07 follow-ups: one spawn-and-kill code for every killable child, no dead in-process render."""

from __future__ import annotations

from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "module",
    [
        "core/regex_isolated.py",
        "core/textfsm_isolated.py",
        "services/ai_assistant/render_isolated.py",
        "workflow_steps/common/jinja_render.py",
        "workflow_steps/common/regex_search.py",
    ],
)
def test_every_isolated_runner_spawns_through_isolated_process(module: str) -> None:
    source = (BACKEND / module).read_text()

    assert "create_subprocess_exec" not in source
    assert "run_child" in source


def test_the_template_service_has_no_in_process_render() -> None:
    from services.templates import templates_service

    assert not hasattr(templates_service.TemplatesService, "render")
    assert not hasattr(templates_service, "_jinja_env")
