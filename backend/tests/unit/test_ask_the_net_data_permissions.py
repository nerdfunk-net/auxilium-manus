"""``ASK_THE_NET_DATA_PERMISSIONS`` (frontend) must name exactly the permissions that attach tools.

The Ask the Net page tells a user who holds none of them that Batfish, Nautobot, runs and reports
are out of reach. That is only true if every listed permission, held alone, makes
``build_general_session`` attach tools, and no permission that attaches tools alone is missing from
the list (review 2026-11-13: config backups and released workflows attach nothing without Batfish
or the run reader).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.surfaces import build_general_session

FRONTEND_CONSTANTS = (
    Path(__file__).resolve().parents[3]
    / "frontend/src/components/features/ask-the-net/constants/ask-the-net.ts"
)

# Permission -> the reader the chat route builds from it (routers/ai_assistant.py ``_session_for``),
# when that permission is the only one the user holds. The comment names the condition, if any.
ATTACHES_ALONE: dict[tuple[str, str], str] = {
    ("sources.nautobot", "read"): "nautobot_reader",  # and a configured Nautobot source
    ("sources.catalyst_center", "read"): "catalyst_reader",
    ("sources.aci", "read"): "aci_reader",
    ("client_data", "read"): "client_data_reader",
    ("workflow_runs", "read"): "run_reader",
    ("reports", "read"): "report_reader",
}
# Held alone these attach nothing (the reader is built but the session does not use it).
ATTACHES_NOTHING_ALONE: dict[tuple[str, str], str] = {
    ("git.files", "read"): "config_reader",  # config backups live inside the Batfish branch
    ("workflows", "execute"): "released_reader",  # needs the run reader as well
}


class _Unused:
    """Stands in for a reader the session only stores."""


def _tool_names(**readers: Any) -> set[str]:
    session = build_general_session(
        user_id=1,
        reader=_Unused(),  # type: ignore[arg-type]
        store=None,
        sharing=SharingPolicy(),
        may_query_batfish=False,
        **readers,
    )
    return {spec.name for spec in session.toolbox.specs()}


def _listed_in_frontend() -> set[tuple[str, str]]:
    text = FRONTEND_CONSTANTS.read_text()
    block = text.split("ASK_THE_NET_DATA_PERMISSIONS", 1)[1].split("];", 1)[0]
    return set(re.findall(r'\["([a-z_.]+)",\s*"([a-z_]+)"\]', block))


@pytest.mark.parametrize(("permission", "reader"), sorted(ATTACHES_ALONE.items()))
def test_each_listed_permission_attaches_tools_by_itself(
    permission: tuple[str, str], reader: str
) -> None:
    assert _tool_names(**{reader: _Unused()}), f"{permission} alone attaches no tool"


@pytest.mark.parametrize(("permission", "reader"), sorted(ATTACHES_NOTHING_ALONE.items()))
def test_permissions_that_attach_nothing_alone_are_not_listed(
    permission: tuple[str, str], reader: str
) -> None:
    assert _tool_names(**{reader: _Unused()}) == set(), f"{permission} alone attaches tools"
    assert permission not in _listed_in_frontend()


def test_batfish_query_attaches_tools_by_itself() -> None:
    session = build_general_session(
        user_id=1,
        reader=_Unused(),  # type: ignore[arg-type]
        store=None,
        sharing=SharingPolicy(),
        may_query_batfish=True,
    )
    assert session.toolbox.specs()


def test_the_frontend_list_is_exactly_batfish_plus_what_attaches_alone() -> None:
    assert _listed_in_frontend() == {("sources.batfish", "query"), *ATTACHES_ALONE}


def test_released_workflows_need_the_run_reader_too() -> None:
    names = _tool_names(released_reader=_Unused(), run_reader=_Unused())
    assert "propose_workflow_run" in names


def test_the_dns_tool_has_no_permission_and_is_offered_by_the_operator_switch_alone() -> None:
    """The page's note must not claim 'nothing readable' for a user whose session has DNS."""
    assert "get_dns_lookup" in _tool_names(dns_resolver=_Unused())
