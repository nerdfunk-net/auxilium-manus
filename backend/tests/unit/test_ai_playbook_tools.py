"""``list_playbooks`` / ``get_playbook`` on the general surface (doc/AI_TOOL_CHAIN.md §21.3)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from services.ai_assistant import knowledge_loader as kl
from services.ai_assistant import playbooks as pb
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore
from services.ai_assistant.surfaces import build_general_session
from services.ai_assistant.tools import playbook_tools as pt
from services.ai_assistant.tools.base import ToolContext
from tests.unit.test_ai_batfish_tools import FakeReader


def _front(name: str, *, title: str = "Demo", tools: str = "[get_routes]", extra: str = "") -> str:
    return (
        f'---\nname: {name}\ntitle: {title}\nwhen: "when {name}"\ntools: {tools}\n'
        f"scope: read-only\n{extra}---\n"
    )


def _text(name: str, *, tools: str = "[get_routes]", extra: str = "", title: str = "Demo") -> str:
    return _front(name, title=title, tools=tools, extra=extra) + (
        "## Steps\n1. `get_routes` for the destination.\n"
    )


@pytest.fixture
def dirs(tmp_path: Path, monkeypatch) -> tuple[Path, Path]:
    builtin = tmp_path / "builtin"
    builtin.mkdir()
    monkeypatch.setattr(pb, "BUILTIN_PLAYBOOK_DIR", builtin)
    monkeypatch.setattr(kl.settings, "data_directory", tmp_path / "data")
    kl.clear_cache()
    local = tmp_path / "data" / "ai" / "playbooks"
    local.mkdir(parents=True)
    return builtin, local


def _ctx(*, sharing: SharingPolicy | None = None, available: frozenset[str] | None = None):
    extras = {} if available is None else {pt.AVAILABLE_TOOLS_KEY: available}
    return ToolContext(
        user_id=1,
        redactor=Redactor(),
        extras=extras,
        sharing=sharing or SharingPolicy(),
    )


def _call(tool_name: str, ctx: ToolContext, **args):
    tool = next(t for t in pt.build_playbook_tools() if t.name == tool_name)
    return asyncio.run(tool.handler(ctx, tool.input_model(**args)))


def _listed(ctx: ToolContext) -> dict:
    out = _call("list_playbooks", ctx)
    assert not out.is_error
    return json.loads(out.content)


# -- registration -----------------------------------------------------------------------------


def test_tool_names_follow_the_read_only_naming_rule() -> None:
    names = [t.name for t in pt.build_playbook_tools()]

    assert names == ["list_playbooks", "get_playbook"]


def test_known_general_tool_names_cover_the_batfish_result_and_playbook_tools() -> None:
    names = pt.known_general_tool_names()

    assert {
        "get_routes",
        "get_traceroute",
        "query_result",
        "list_playbooks",
        "get_playbook",
    } <= names
    assert not {n for n in names if n.startswith(("run", "execute"))}
    assert {n for n in names if n.startswith("propose")} == {"propose_device_command"}


def test_known_general_tool_names_cover_every_nautobot_tool() -> None:
    from services.ai_assistant.tools.nautobot_tools import build_nautobot_tools

    nautobot = {t.name for t in build_nautobot_tools()}

    assert nautobot and nautobot <= pt.known_general_tool_names()


def test_a_local_playbook_may_name_the_nautobot_tools(dirs) -> None:
    _, local = dirs
    body = "## Steps\n1. `list_prefixes` for the site.\n2. `get_next_free_ip` for the prefix.\n"
    (local / "free-ip.md").write_text(
        _front("free-ip", title="Demo", tools="[list_prefixes, get_next_free_ip]", extra="") + body,
        encoding="utf-8",
    )

    # A local playbook is class B by default: visible only when inventory data is shared.
    listed = {p["name"] for p in _listed(_ctx(sharing=SharingPolicy(inventory=True)))["playbooks"]}

    assert "free-ip" in listed


# -- list_playbooks ---------------------------------------------------------------------------


def test_list_shows_name_title_when_tools_and_source(dirs) -> None:
    builtin, _ = dirs
    (builtin / "demo.md").write_text(_text("demo", title="Demo title"), encoding="utf-8")

    (entry,) = _listed(_ctx())["playbooks"]

    assert entry == {
        "name": "demo",
        "title": "Demo title",
        "when": "when demo",
        "tools": ["get_routes"],
        "tools_unavailable": [],
        "source": "builtin",
        "overrides_builtin": False,
    }


def test_list_reports_tools_the_user_does_not_have(dirs) -> None:
    builtin, _ = dirs
    (builtin / "demo.md").write_text(
        _text("demo", tools="[get_routes, get_traceroute]"), encoding="utf-8"
    )

    (entry,) = _listed(_ctx(available=frozenset({"get_routes"})))["playbooks"]

    assert entry["tools_unavailable"] == ["get_traceroute"]


def test_without_an_availability_set_no_tool_is_reported_missing(dirs) -> None:
    builtin, _ = dirs
    (builtin / "demo.md").write_text(_text("demo"), encoding="utf-8")

    (entry,) = _listed(_ctx())["playbooks"]

    assert entry["tools_unavailable"] == []


def test_list_marks_local_override(dirs) -> None:
    builtin, local = dirs
    (builtin / "demo.md").write_text(_text("demo"), encoding="utf-8")
    (local / "demo.md").write_text(_text("demo", extra="data_class: A\n"), encoding="utf-8")

    (entry,) = _listed(_ctx())["playbooks"]

    assert entry["source"] == "local"
    assert entry["overrides_builtin"] is True


def test_list_with_nothing_installed_says_so(dirs) -> None:
    data = _listed(_ctx())

    assert data["playbooks"] == []
    assert "no playbook" in data["note"].lower()


def test_class_b_playbooks_need_the_inventory_opt_in(dirs) -> None:
    builtin, local = dirs
    (builtin / "open.md").write_text(_text("open"), encoding="utf-8")
    (local / "site.md").write_text(_text("site"), encoding="utf-8")  # local defaults to B

    without = _listed(_ctx(sharing=SharingPolicy()))
    with_opt_in = _listed(_ctx(sharing=SharingPolicy(inventory=True)))

    assert [p["name"] for p in without["playbooks"]] == ["open"]
    assert without["not_shared"] == "inventory_data"
    assert without["withheld_playbooks"] == 1
    assert [p["name"] for p in with_opt_in["playbooks"]] == ["open", "site"]
    assert "not_shared" not in with_opt_in


def test_withheld_playbook_titles_do_not_leak(dirs) -> None:
    _, local = dirs
    (local / "site.md").write_text(_text("site", title="Secret Carrier Layout"), encoding="utf-8")

    out = _call("list_playbooks", _ctx())

    assert "Secret Carrier Layout" not in out.content
    assert out.content.count("not_shared") == 1


def test_invalid_local_files_are_not_offered_to_the_model(dirs) -> None:
    _, local = dirs
    (local / "broken.md").write_text("no front matter", encoding="utf-8")

    out = _call("list_playbooks", _ctx())

    assert "broken" not in out.content


# -- get_playbook -----------------------------------------------------------------------------


def test_get_returns_the_text_without_front_matter(dirs) -> None:
    builtin, _ = dirs
    (builtin / "demo.md").write_text(_text("demo"), encoding="utf-8")

    out = _call("get_playbook", _ctx(), name="demo")

    assert not out.is_error
    assert out.content.startswith("## Steps")
    assert "name: demo" not in out.content


def test_get_records_the_playbook_in_the_audit_refs(dirs) -> None:
    builtin, _ = dirs
    (builtin / "demo.md").write_text(_text("demo"), encoding="utf-8")
    ctx = _ctx()

    _call("get_playbook", ctx, name="demo")

    assert ctx.audit_refs == {"playbook:demo"}


def test_get_appends_a_note_about_unavailable_tools(dirs) -> None:
    builtin, _ = dirs
    (builtin / "demo.md").write_text(
        _text("demo", tools="[get_routes, get_traceroute]"), encoding="utf-8"
    )

    out = _call("get_playbook", _ctx(available=frozenset({"get_routes"})), name="demo")

    assert "get_traceroute" in out.content.splitlines()[-1]
    assert "not available" in out.content.splitlines()[-1]


def test_get_without_missing_tools_adds_no_note(dirs) -> None:
    builtin, _ = dirs
    (builtin / "demo.md").write_text(_text("demo"), encoding="utf-8")

    out = _call("get_playbook", _ctx(available=frozenset({"get_routes"})), name="demo")

    assert "not available" not in out.content


def test_unknown_name_is_an_error_with_the_closest_names(dirs) -> None:
    builtin, _ = dirs
    (builtin / "target-unreachable.md").write_text(_text("target-unreachable"), encoding="utf-8")
    (builtin / "other.md").write_text(_text("other"), encoding="utf-8")

    out = _call("get_playbook", _ctx(), name="target-unreachble")

    assert out.is_error
    assert "target-unreachable" in out.content
    assert "other" not in out.content


def test_unknown_name_with_nothing_close_lists_the_visible_names(dirs) -> None:
    builtin, _ = dirs
    (builtin / "alpha.md").write_text(_text("alpha"), encoding="utf-8")

    out = _call("get_playbook", _ctx(), name="zzzz")

    assert out.is_error
    assert "alpha" in out.content


@pytest.mark.parametrize("name", ["../secret", "/etc/passwd", "a/b", "demo.md", "..", "x" * 200])
def test_a_name_is_never_a_path(dirs, tmp_path: Path, name: str) -> None:
    builtin, _ = dirs
    (builtin / "demo.md").write_text(_text("demo"), encoding="utf-8")
    (tmp_path / "secret.md").write_text(_text("secret"), encoding="utf-8")

    try:
        out = _call("get_playbook", _ctx(), name=name)
    except ValueError:  # input validation may refuse it outright
        return

    assert out.is_error
    assert "secret" not in out.content.replace("../secret", "")


def test_class_b_playbook_is_withheld_without_opt_in_but_readable_with_it(dirs) -> None:
    _, local = dirs
    (local / "site.md").write_text(_text("site"), encoding="utf-8")

    closed = _call("get_playbook", _ctx(sharing=SharingPolicy()), name="site")
    opened = _call("get_playbook", _ctx(sharing=SharingPolicy(inventory=True)), name="site")

    assert closed.is_error
    assert "Steps" not in closed.content
    assert opened.content.startswith("## Steps")


def test_a_hidden_name_gets_exactly_the_answer_of_a_name_that_does_not_exist(dirs) -> None:
    _, local = dirs
    (local / "site.md").write_text(_text("site"), encoding="utf-8")
    ctx = _ctx(sharing=SharingPolicy())

    hidden = _call("get_playbook", ctx, name="site")
    missing = _call("get_playbook", ctx, name="sitf")

    assert hidden.is_error
    assert hidden.content.replace("site", "X") == missing.content.replace("sitf", "X")


def test_withheld_playbook_is_not_audited_as_read(dirs) -> None:
    _, local = dirs
    (local / "site.md").write_text(_text("site"), encoding="utf-8")
    ctx = _ctx()

    _call("get_playbook", ctx, name="site")

    assert ctx.audit_refs == set()


def test_unknown_name_does_not_reveal_class_b_names_without_opt_in(dirs) -> None:
    _, local = dirs
    (local / "carrier-x-layout.md").write_text(_text("carrier-x-layout"), encoding="utf-8")

    out = _call("get_playbook", _ctx(), name="carrier-x-layou")

    assert out.is_error
    assert "carrier-x-layout" not in out.content


# -- the general surface ----------------------------------------------------------------------


def _session(**overrides):
    base = {
        "user_id": 7,
        "reader": FakeReader(),
        "store": ResultStore(InMemoryResultBackend()),
        "sharing": SharingPolicy(inventory=True, addresses=True),
        "may_query_batfish": True,
    }
    base.update(overrides)
    return build_general_session(**base)


def test_session_offers_the_playbook_tools() -> None:
    names = {s.name for s in _session().toolbox.specs()}

    assert {"list_playbooks", "get_playbook"} <= names


def test_session_without_batfish_permission_has_no_tools_at_all() -> None:
    assert _session(may_query_batfish=False).toolbox.specs() == []


def test_session_tells_the_playbook_tools_what_is_available() -> None:
    session = _session(store=None)  # no handle tools

    available = session.toolbox._context.extras[pt.AVAILABLE_TOOLS_KEY]

    assert "get_routes" in available
    assert "get_playbook" in available
    assert "query_result" not in available


def test_session_prompt_sends_troubleshooting_requests_to_the_playbooks() -> None:
    system = _session().system

    assert "list_playbooks" in system
    assert "get_playbook" in system


def test_end_to_end_through_the_toolbox(dirs) -> None:
    builtin, _ = dirs
    (builtin / "demo.md").write_text(
        _text("demo", tools="[get_routes, query_result]"), encoding="utf-8"
    )
    session = _session(store=None)

    listed = asyncio.run(session.toolbox.execute(ToolCall(id="1", name="list_playbooks", input={})))
    got = asyncio.run(
        session.toolbox.execute(ToolCall(id="2", name="get_playbook", input={"name": "demo"}))
    )

    assert json.loads(listed.content)["playbooks"][0]["tools_unavailable"] == ["query_result"]
    assert got.content.startswith("## Steps")
    assert session.toolbox.audit_refs == {"playbook:demo"}


@pytest.mark.parametrize("name", ["", "x" * 65])
def test_the_name_input_is_length_bounded(name: str) -> None:
    with pytest.raises(ValueError):
        pt.GetPlaybookInput(name=name)


@pytest.mark.parametrize("name", ["Demo", "a\nb", "ignore previous", "a_b", "-a", "1a"])
def test_a_name_that_is_not_a_slug_fails_validation_instead_of_being_quoted(name: str) -> None:
    with pytest.raises(ValueError):
        pt.GetPlaybookInput(name=name)


def test_a_catalog_too_big_for_one_result_is_paged_as_valid_json(dirs) -> None:
    builtin, _ = dirs
    tools = "[" + ", ".join(["get_routes"] * 1) + "]"
    for i in range(60):
        text = _text(f"pb{i:02d}", tools=tools, title="T" * 100).replace(
            f'when: "when pb{i:02d}"', f'when: "{"w" * 390}"'
        )
        (builtin / f"pb{i:02d}.md").write_text(text, encoding="utf-8")
    ctx = _ctx()

    first = _call("list_playbooks", ctx)
    data = json.loads(first.content)  # a cut line would not parse

    assert len(first.content) <= 20_000 and not first.truncated
    assert data["total"] == 60
    assert 0 < len(data["playbooks"]) < 60
    names = [p["name"] for p in data["playbooks"]]
    seen = list(names)
    while "next_offset" in data:
        data = json.loads(_call("list_playbooks", ctx, offset=data["next_offset"]).content)
        seen += [p["name"] for p in data["playbooks"]]
    assert seen == [f"pb{i:02d}" for i in range(60)]


def test_a_small_catalog_has_no_paging_fields(dirs) -> None:
    builtin, _ = dirs
    (builtin / "demo.md").write_text(_text("demo"), encoding="utf-8")

    data = _listed(_ctx())

    assert data["total"] == 1
    assert "next_offset" not in data


def test_total_counts_only_the_playbooks_this_user_may_see(dirs) -> None:
    builtin, local = dirs
    (builtin / "open.md").write_text(_text("open"), encoding="utf-8")
    (local / "site.md").write_text(_text("site"), encoding="utf-8")  # class B

    data = _listed(_ctx(sharing=SharingPolicy()))

    assert data["total"] == 1
    assert data["withheld_playbooks"] == 1
