"""Playbook files: format, validation, built-in/local merge (doc/AI_TOOL_CHAIN.md §21, §25)."""

from __future__ import annotations

from pathlib import Path

import pytest

from services.ai_assistant import knowledge_loader as kl
from services.ai_assistant import playbooks as pb

KNOWN = frozenset({"get_routes", "get_traceroute", "analyze_acl", "list_playbooks"})


@pytest.fixture(autouse=True)
def _clean_cache() -> None:
    kl.clear_cache()


def _text(
    name: str = "demo",
    *,
    front: str | None = None,
    body: str | None = None,
    extra_front: str = "",
) -> str:
    if front is None:
        front = (
            f"name: {name}\n"
            "title: Demo playbook\n"
            'when: "something cannot be reached"\n'
            "tools: [get_routes, get_traceroute]\n"
            "scope: read-only\n"
            f"{extra_front}"
        )
    if body is None:
        body = (
            "# Demo\n\n## When to use\nAlways.\n\n## Steps\n"
            "1. `get_traceroute` with `trace_format=summary` and `only_problems`.\n"
            "2. `get_routes` for the destination.\n"
        )
    return f"---\n{front}---\n{body}"


def _parse(text: str, *, name: str = "demo", source: str = "builtin") -> pb.Playbook | pb.Disabled:
    return pb.parse_playbook(text, file_stem=name, source=source, known_tools=KNOWN)


def _reason(text: str, *, name: str = "demo", source: str = "builtin") -> str:
    with pytest.raises(pb.PlaybookError) as info:
        _parse(text, name=name, source=source)
    return str(info.value)


# -- parsing ----------------------------------------------------------------------------------


def test_valid_playbook_is_parsed() -> None:
    parsed = _parse(_text())

    assert isinstance(parsed, pb.Playbook)
    assert parsed.name == "demo"
    assert parsed.title == "Demo playbook"
    assert parsed.when == "something cannot be reached"
    assert parsed.tools == ("get_routes", "get_traceroute")
    assert parsed.source == "builtin"
    assert parsed.data_class == "A"
    assert parsed.body.startswith("# Demo")
    assert "---" not in parsed.body.splitlines()[0]


def test_data_class_defaults_to_a_for_builtin_and_b_for_local() -> None:
    assert _parse(_text()).data_class == "A"  # type: ignore[union-attr]
    assert _parse(_text(), source="local").data_class == "B"  # type: ignore[union-attr]


def test_data_class_can_be_set_explicitly_in_both_directions() -> None:
    assert _parse(_text(extra_front="data_class: A\n"), source="local").data_class == "A"  # type: ignore[union-attr]
    assert _parse(_text(extra_front="data_class: B\n")).data_class == "B"  # type: ignore[union-attr]


@pytest.mark.parametrize("value", ["C", "a", "inventory", "1"])
def test_data_class_must_be_a_or_b(value: str) -> None:
    assert "data_class" in _reason(_text(extra_front=f"data_class: {value!r}\n"))


def test_file_without_front_matter_is_invalid() -> None:
    assert "must start" in _reason("# Just text\n## Steps\n")


def test_front_matter_must_be_the_first_thing_in_the_file() -> None:
    assert "must start" in _reason("intro\n" + _text())


def test_unterminated_front_matter_is_invalid() -> None:
    assert "not closed" in _reason("---\nname: demo\n# no end\n")


def test_front_matter_that_is_not_valid_yaml_is_invalid() -> None:
    assert "front matter" in _reason(_text(front="name: [unclosed\n"))


def test_front_matter_that_is_not_a_mapping_is_invalid() -> None:
    assert "mapping" in _reason(_text(front="- a\n- b\n"))


def test_overlong_front_matter_is_invalid() -> None:
    padding = "# " + "x" * pb.MAX_FRONT_MATTER_CHARS + "\n"

    assert "longer" in _reason(_text(front=_text().split("---\n")[1] + padding))


def test_blank_title_is_invalid() -> None:
    front = _text().split("---\n")[1].replace("title: Demo playbook", "title: '  '")

    assert "title" in _reason(_text(front=front))


def test_unknown_front_matter_key_is_invalid() -> None:
    assert "shell" in _reason(_text(extra_front="shell: yes\n"))


def test_name_must_equal_the_file_name() -> None:
    assert "file name" in _reason(_text("other"), name="demo")


@pytest.mark.parametrize("name", ["Demo", "a_b", "-a", "a b", "x" * 65, "1abc"])
def test_name_must_be_a_lowercase_slug(name: str) -> None:
    assert "name" in _reason(_text(name), name=name)


@pytest.mark.parametrize("field", ["title", "when", "tools", "scope", "name"])
def test_required_fields(field: str) -> None:
    front = "\n".join(
        line for line in _text().split("---\n")[1].splitlines() if not line.startswith(f"{field}:")
    )

    assert field in _reason(_text(front=front + "\n"))


def test_title_and_when_are_length_capped() -> None:
    assert "title" in _reason(
        _text(front=_text().split("---\n")[1].replace("Demo playbook", "t" * 200))
    )
    assert "when" in _reason(
        _text(front=_text().split("---\n")[1].replace("something cannot be reached", "w" * 600))
    )


def test_scope_must_be_read_only() -> None:
    front = _text().split("---\n")[1].replace("read-only", "read-write")

    assert "scope" in _reason(_text(front=front))


def test_a_tool_that_does_not_exist_is_reported_by_name() -> None:
    front = _text().split("---\n")[1].replace("get_routes,", "get_routez,")

    assert "get_routez" in _reason(_text(front=front))


def test_tools_must_be_a_list_of_strings() -> None:
    front = _text().split("---\n")[1].replace("[get_routes, get_traceroute]", "get_routes")

    assert "tools" in _reason(_text(front=front))


def test_at_most_twenty_tools() -> None:
    front = (
        _text()
        .split("---\n")[1]
        .replace("[get_routes, get_traceroute]", "[" + ", ".join(["get_routes"] * 21) + "]")
    )

    body = "## Steps\n1. `get_routes` only.\n"

    assert "more than" in _reason(_text(front=front, body=body))


def test_tools_must_all_be_strings() -> None:
    front = _text().split("---\n")[1].replace("[get_routes, get_traceroute]", "[1, 2]")

    assert "list of tool names" in _reason(_text(front=front))


def test_repeated_tool_names_are_listed_once() -> None:
    front = (
        _text()
        .split("---\n")[1]
        .replace("[get_routes, get_traceroute]", "[get_routes, get_traceroute, get_routes]")
    )

    assert _parse(_text(front=front)).tools == ("get_routes", "get_traceroute")  # type: ignore[union-attr]


def test_a_tool_named_in_the_steps_must_be_declared_in_the_front_matter() -> None:
    body = "## Steps\n1. `analyze_acl` on the device.\n"

    assert "does not list" in _reason(_text(body=body))


def test_an_unknown_tool_named_in_the_steps_is_reported() -> None:
    body = "## Steps\n1. `get_nothing_here` on the device.\n"

    reason = _reason(_text(body=body))

    assert "get_nothing_here" in reason
    assert "does not exist" in reason


def test_a_forbidden_tool_prefix_named_in_the_steps_is_reported() -> None:
    body = "## Steps\n1. `run_command` on the device.\n"

    assert "run_command" in _reason(_text(body=body))


def test_parameter_names_in_the_steps_are_not_mistaken_for_tools() -> None:
    body = "## Steps\n1. `get_routes` with `prefix_match_type=exact`, `only_problems`.\n"

    assert isinstance(_parse(_text(body=body)), pb.Playbook)


def test_the_steps_section_is_required() -> None:
    assert "Steps" in _reason(_text(body="# Demo\n\n## When to use\nAlways.\n"))


@pytest.mark.parametrize(
    "command",
    [
        "conf t",
        "configure terminal",
        "Configure Terminal",
        "reload",
        "write memory",
        "write erase",
        "copy running-config startup-config",
        "copy tftp: running-config",
    ],
)
def test_configuration_commands_are_refused(command: str) -> None:
    body = f"## Steps\n1. Send `{command}` to the device.\n"

    assert "configuration command" in _reason(_text(body=body))


@pytest.mark.parametrize(
    "prose",
    [
        "Read the running configuration of the filter.",
        "Write the report as a list.",
        "Copy the handle into the next call.",
        "A routing table that is not up to date.",
    ],
)
def test_ordinary_prose_is_not_mistaken_for_a_command(prose: str) -> None:
    body = f"## Steps\n1. {prose}\n"

    assert isinstance(_parse(_text(body=body)), pb.Playbook)


def test_playbook_larger_than_the_limit_is_invalid(tmp_path: Path) -> None:
    builtin = tmp_path / "b"
    builtin.mkdir()
    (builtin / "demo.md").write_text(
        _text(body="## Steps\n" + "x" * pb.MAX_PLAYBOOK_CHARS), encoding="utf-8"
    )

    result = pb.load_playbooks(known_tools=KNOWN, builtin_dir=builtin, local_dir=tmp_path / "none")

    assert not result.playbooks
    assert "too large" in result.invalid[0].reason


def test_playbook_exactly_at_the_limit_is_accepted(tmp_path: Path) -> None:
    builtin = tmp_path / "b"
    builtin.mkdir()
    head = _text(body="## Steps\n")
    text = head + "x" * (pb.MAX_PLAYBOOK_CHARS - len(head))
    (builtin / "demo.md").write_text(text, encoding="utf-8")

    result = pb.load_playbooks(known_tools=KNOWN, builtin_dir=builtin, local_dir=tmp_path / "none")

    assert [p.name for p in result.playbooks] == ["demo"]


# -- disabled ---------------------------------------------------------------------------------


def test_local_file_can_disable_a_name_with_minimal_front_matter() -> None:
    parsed = _parse("---\nname: demo\ndisabled: true\n---\n", source="local")

    assert parsed == pb.Disabled(name="demo")


def test_disabled_is_not_allowed_in_a_builtin_file() -> None:
    assert "disabled" in _reason("---\nname: demo\ndisabled: true\n---\n")


def test_disabled_false_is_an_ordinary_playbook() -> None:
    assert isinstance(_parse(_text(extra_front="disabled: false\n"), source="local"), pb.Playbook)


def test_disabled_must_be_a_boolean() -> None:
    assert "disabled" in _reason(_text(extra_front="disabled: 'yes please'\n"), source="local")


# -- loading and merging ----------------------------------------------------------------------


def _write(directory: Path, name: str, text: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.md").write_text(text, encoding="utf-8")


def _load(tmp_path: Path) -> pb.PlaybookSet:
    return pb.load_playbooks(
        known_tools=KNOWN, builtin_dir=tmp_path / "builtin", local_dir=tmp_path / "local"
    )


def test_missing_directories_give_an_empty_set(tmp_path: Path) -> None:
    result = _load(tmp_path)

    assert result.playbooks == ()
    assert result.invalid == ()


def test_builtin_and_local_only_playbooks_are_merged_and_sorted(tmp_path: Path) -> None:
    _write(tmp_path / "builtin", "zeta", _text("zeta"))
    _write(tmp_path / "local", "alpha", _text("alpha"))

    result = _load(tmp_path)

    assert [(p.name, p.source) for p in result.playbooks] == [
        ("alpha", "local"),
        ("zeta", "builtin"),
    ]
    assert not any(p.overrides_builtin for p in result.playbooks)


def test_local_playbook_overrides_the_builtin_one_of_the_same_name(tmp_path: Path) -> None:
    _write(tmp_path / "builtin", "demo", _text())
    _write(
        tmp_path / "local",
        "demo",
        _text(front=_text().split("---\n")[1].replace("Demo playbook", "Site version")),
    )

    (result,) = _load(tmp_path).playbooks

    assert result.title == "Site version"
    assert result.source == "local"
    assert result.overrides_builtin is True


def test_local_disabled_file_hides_the_builtin_playbook(tmp_path: Path) -> None:
    _write(tmp_path / "builtin", "demo", _text())
    _write(tmp_path / "local", "demo", "---\nname: demo\ndisabled: true\n---\n")

    result = _load(tmp_path)

    assert result.playbooks == ()
    assert result.invalid == ()


def test_invalid_local_file_is_reported_and_does_not_override_the_builtin(tmp_path: Path) -> None:
    _write(tmp_path / "builtin", "demo", _text())
    _write(tmp_path / "local", "demo", "no front matter at all")

    result = _load(tmp_path)

    assert [(p.name, p.source) for p in result.playbooks] == [("demo", "builtin")]
    assert [(i.source, i.file) for i in result.invalid] == [("local", "demo.md")]
    assert "front matter" in result.invalid[0].reason


def test_invalid_local_file_is_logged(tmp_path: Path, caplog) -> None:
    _write(tmp_path / "local", "demo", "nope")

    with caplog.at_level("WARNING", logger=pb.logger.name):
        _load(tmp_path)

    assert "demo.md" in caplog.text


def test_files_starting_with_an_underscore_and_other_extensions_are_ignored(tmp_path: Path) -> None:
    _write(tmp_path / "local", "_template", _text("_template"))
    (tmp_path / "local" / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "local" / "sub").mkdir()
    (tmp_path / "local" / "folder.md").mkdir()

    result = _load(tmp_path)

    assert result.playbooks == ()
    assert result.invalid == ()


def test_file_that_is_not_utf8_is_invalid_not_a_crash(tmp_path: Path) -> None:
    (tmp_path / "local").mkdir()
    (tmp_path / "local" / "demo.md").write_bytes(b"\xff\xfe\x00")

    result = _load(tmp_path)

    assert result.playbooks == ()
    assert result.invalid[0].file == "demo.md"


def test_only_the_first_hundred_files_per_directory_are_read(tmp_path: Path) -> None:
    for i in range(pb.MAX_FILES_PER_DIR + 5):
        _write(tmp_path / "local", f"p{i:03d}", _text(f"p{i:03d}"))

    result = _load(tmp_path)

    assert len(result.playbooks) == pb.MAX_FILES_PER_DIR
    assert any("limit" in i.reason for i in result.invalid)


def test_edit_of_a_local_file_is_live_without_restart(tmp_path: Path) -> None:
    import os

    _write(tmp_path / "local", "demo", _text())
    first = _load(tmp_path).playbooks[0].title
    path = tmp_path / "local" / "demo.md"
    path.write_text(path.read_text().replace("Demo playbook", "Changed"), encoding="utf-8")
    os.utime(path, ns=(5, 5))

    assert first == "Demo playbook"
    assert _load(tmp_path).playbooks[0].title == "Changed"


def test_default_directories_are_the_package_folder_and_the_data_volume(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(kl.settings, "data_directory", tmp_path)
    _write(tmp_path / "ai" / "playbooks", "site", _text("site"))

    result = pb.load_playbooks(known_tools=KNOWN)

    assert pb.BUILTIN_PLAYBOOK_DIR == kl.KNOWLEDGE_DIR / "playbooks"
    assert "site" in [p.name for p in result.playbooks]


# -- the shipped playbooks --------------------------------------------------------------------


def test_every_shipped_playbook_is_valid_for_the_general_surface() -> None:
    from services.ai_assistant.tools.playbook_tools import known_general_tool_names

    result = pb.load_playbooks(
        known_tools=known_general_tool_names(), local_dir=Path("/nonexistent/playbooks")
    )

    assert result.invalid == ()
    assert "target-unreachable" in [p.name for p in result.playbooks]
    assert all(p.source == "builtin" and p.data_class == "A" for p in result.playbooks)


def test_where_is_this_host_playbook_orders_nautobot_client_data_then_aci() -> None:
    from services.ai_assistant.tools.playbook_tools import known_general_tool_names

    result = pb.load_playbooks(
        known_tools=known_general_tool_names(), local_dir=Path("/nonexistent/playbooks")
    )
    (playbook,) = [p for p in result.playbooks if p.name == "where-is-this-host"]

    assert {"find_client", "get_client_data_coverage", "find_aci_endpoint"} <= set(playbook.tools)
    body = " ".join(playbook.body.split())  # line breaks do not matter for the wording
    # The order is the point: documented, then stored observations, then coverage, then ACI.
    steps = body[body.index("## Steps") : body.index("## Decision points")]
    positions = [
        steps.index(tool)
        for tool in (
            "list_ip_addresses",
            "find_client",
            "get_client_data_coverage",
            "find_aci_endpoint",
        )
    ]
    assert positions == sorted(positions)
    # The answer must carry the age and the limits of stored data.
    assert "quote its age (`age_seconds`" in body
    assert "`ip_age_seconds`" in body
    assert "`neighbor` is certain" in body
    assert "`mac_count` is only a heuristic" in body
    assert "Report `likely_location`" in body
    assert 'never "the host does not exist"' in body
    # "Find the IP address X" must reach this playbook, and a config-only answer must not stand.
    assert "find the ip address" in playbook.when.lower()
    assert "not configured on any device" in body
    assert "Batfish" in body and "Nautobot" in body
    assert "network device" in body and "not in the model" in body
    assert "report both sources" in body
    assert '"Find the IP address X" is not finished by' in body
    assert "Always call `find_client` too" in body
    # With client data and ACI both configured, one call asks both sources.
    assert "find_host" in playbook.tools
    assert "If `find_host` is offered" in body


# -- review findings ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "erase startup-config",
        "wr mem",
        "wr",
        "copy run start",
        "copy running-config",
        "commit",
        "commit confirmed",
        "request system reboot",
        "clear ip bgp *",
        "no shutdown",
        "reload in 5",
    ],
)
def test_more_change_commands_are_refused(command: str) -> None:
    for body in (
        f"## Steps\n1. Send `{command}` to the device.\n",
        f"## Steps\n```\n{command}\n```\n",
        f"## Steps\n- {command}\n",
    ):
        assert "configuration command" in _reason(_text(body=body)), body


@pytest.mark.parametrize(
    "prose",
    [
        "If the device was reloaded, the snapshot is stale.",
        "Do not reload anything; this playbook only reads.",
        "The configuration was taken before the reload.",
        "Commit to one cause before you report.",
        "Reload the question with a narrower prefix.",
        "Clear the filter and ask again.",
    ],
)
def test_prose_that_mentions_command_words_is_allowed(prose: str) -> None:
    assert isinstance(_parse(_text(body=f"## Steps\n1. {prose}\n")), pb.Playbook)


def test_title_and_when_are_checked_for_commands() -> None:
    front = _text().split("---\n")[1]

    assert "configuration command" in _reason(
        _text(front=front.replace("title: Demo playbook", "title: conf t"))
    )
    assert "configuration command" in _reason(
        _text(front=front.replace("something cannot be reached", "reload in 5"))
    )


def test_a_tool_name_is_found_without_backticks_and_with_call_syntax() -> None:
    assert "analyze_acl" in _reason(_text(body="## Steps\n1. Then call analyze_acl on D.\n"))
    assert "analyze_acl" in _reason(_text(body="## Steps\n1. Then `analyze_acl(node)`.\n"))


def test_parameter_assignments_are_not_tool_names() -> None:
    body = "## Steps\n1. `get_routes` with check_filters=true and get_all=1.\n"

    assert isinstance(_parse(_text(body=body)), pb.Playbook)


def test_symlinked_playbook_is_invalid_not_served(tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text(_text("demo"), encoding="utf-8")
    (tmp_path / "local").mkdir()
    (tmp_path / "local" / "demo.md").symlink_to(outside)

    result = _load(tmp_path)

    assert result.playbooks == ()
    assert [(i.file, "regular" in i.reason) for i in result.invalid] == [("demo.md", True)]


def test_fifo_playbook_is_invalid_and_does_not_block(tmp_path: Path) -> None:
    import os
    import signal

    (tmp_path / "local").mkdir()
    os.mkfifo(tmp_path / "local" / "demo.md")
    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(TimeoutError("blocked")))
    signal.alarm(5)
    try:
        result = _load(tmp_path)
    finally:
        signal.alarm(0)

    assert result.playbooks == ()
    assert [i.file for i in result.invalid] == ["demo.md"]


def test_local_class_a_playbook_is_flagged_for_the_operator(tmp_path: Path) -> None:
    _write(tmp_path / "local", "demo", _text(extra_front="data_class: A\n"))

    (entry,) = _load(tmp_path).playbooks

    assert entry.data_class == "A"
    assert pb.shared_with_everyone(entry) is True
    assert pb.shared_with_everyone(_parse(_text())) is False  # type: ignore[arg-type]


def test_a_tool_like_word_inside_a_longer_word_is_not_a_tool_name() -> None:
    body = "## Steps\n1. Do not forget_me_not or IPget_things here.\n"

    assert isinstance(_parse(_text(body=body)), pb.Playbook)
