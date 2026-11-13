"""Ask the Net offers the report tools only with a report reader, and the proposal only to
someone who may generate (reports:write)."""

from __future__ import annotations

from typing import Any

from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.surfaces import build_general_session

READ_TOOLS = {
    "list_report_sources",
    "list_report_datasets",
    "preview_report_query",
    "list_report_templates",
}


class _Unused:
    """Stands in for readers the session only stores."""


def _session(**kw: Any):
    return build_general_session(
        user_id=1,
        reader=_Unused(),  # type: ignore[arg-type]
        store=None,
        sharing=SharingPolicy(),
        may_query_batfish=False,
        **kw,
    )


def _names(session) -> set[str]:
    return {spec.name for spec in session.toolbox.specs()}


def test_without_a_reader_there_are_no_report_tools_and_no_report_prompt() -> None:
    session = _session()
    assert not (_names(session) & (READ_TOOLS | {"propose_report"}))
    assert "write reports" not in session.system


def test_a_reader_gives_the_read_tools_and_the_prompt_but_no_proposal() -> None:
    session = _session(report_reader=_Unused(), can_propose_reports=False)
    assert READ_TOOLS <= _names(session)
    assert "propose_report" not in _names(session)
    assert "write reports" in session.system


def test_the_write_permission_adds_the_proposal() -> None:
    session = _session(report_reader=_Unused(), can_propose_reports=True)
    assert (READ_TOOLS | {"propose_report"}) <= _names(session)


def test_the_report_tools_do_not_need_batfish() -> None:
    session = _session(report_reader=_Unused())
    # Only the report tools exist for a user without Batfish access.
    assert _names(session) == READ_TOOLS
    assert "report tools" in session.system
