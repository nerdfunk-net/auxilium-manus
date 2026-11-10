"""Sections of a backed-up config for Ask the Net (get_config_section)."""

from __future__ import annotations

import asyncio
import json

import pytest
from pydantic import ValidationError

from services.ai_assistant import config_backup as cb
from services.ai_assistant.config_sections import (
    outline,
    select_by_prefix,
    select_by_regex,
    select_by_topic,
    split_sections,
)
from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.results.store import InMemoryResultBackend, ResultStore
from services.ai_assistant.tools import config_backup_tools as tools
from services.ai_assistant.tools.base import ToolContext
from services.ai_assistant.tools.result_tools import RESULT_STORE_KEY

CONFIG = """\
hostname LAB
!
banner motd ^C
router ospf 100 is not here
^C
!
interface GigabitEthernet0/0
 description uplink
 ip address 10.0.0.1 255.255.255.0
!
interface GigabitEthernet0/1
 shutdown
!
router ospf 100
 router-id 1.1.1.1
 network 10.0.0.0 0.0.0.255 area 0
!
router ospf 200 vrf RED
 router-id 2.2.2.2
!
router bgp 65000
 neighbor 10.0.0.2 remote-as 65001
 neighbor 10.0.0.2 password hunter2hunter2
!
ip route 0.0.0.0 0.0.0.0 10.0.0.254
ip routing
route-map RM permit 10
 match ip address 1
!
end
"""


def _headers(sections) -> list[str]:
    return [s.header for s in sections]


def test_split_keeps_children_and_text_and_line_numbers() -> None:
    sections = split_sections(CONFIG)
    ospf = select_by_prefix(sections, "router ospf 100")[0]

    assert ospf.text == ("router ospf 100\n router-id 1.1.1.1\n network 10.0.0.0 0.0.0.255 area 0")
    assert CONFIG.splitlines()[ospf.start_line - 1] == "router ospf 100"
    assert ospf.line_count == 3


def test_a_banner_is_one_section_and_its_text_is_not_a_header() -> None:
    sections = split_sections(CONFIG)

    assert not select_by_prefix(sections, "router ospf 100 is not")
    assert any(h.startswith("banner motd") for h in _headers(sections))
    assert len(select_by_prefix(sections, "router ospf")) == 2


def test_prefix_matches_at_a_word_boundary_and_ignores_case_and_spacing() -> None:
    sections = split_sections(CONFIG)

    assert _headers(select_by_prefix(sections, "ROUTER  OSPF 100")) == ["router ospf 100"]
    assert _headers(select_by_prefix(sections, "ip route")) == [
        "ip route 0.0.0.0 0.0.0.0 10.0.0.254"
    ]  # not "ip routing"
    # no whole-word match: falls back to a plain prefix
    assert len(select_by_prefix(sections, "router osp")) == 2
    assert _headers(select_by_prefix(sections, "interface Gig")) == [
        "interface GigabitEthernet0/0",
        "interface GigabitEthernet0/1",
    ]
    assert not select_by_prefix(sections, "router eigrp")


def test_a_whole_word_match_is_not_widened_by_the_fallback() -> None:
    sections = split_sections("router ospf 1000\n!\nrouter ospf 100\n!\n")

    assert _headers(select_by_prefix(sections, "router ospf 100")) == ["router ospf 100"]


def test_topics() -> None:
    sections = split_sections(CONFIG)

    assert _headers(select_by_topic(sections, "ospf")) == [
        "router ospf 100",
        "router ospf 200 vrf RED",
    ]
    assert set(_headers(select_by_topic(sections, "routing"))) == {
        "router ospf 100",
        "router ospf 200 vrf RED",
        "router bgp 65000",
        "ip route 0.0.0.0 0.0.0.0 10.0.0.254",
        "ip routing",
        "route-map RM permit 10",
    }


LAB_CONFIG = """\
aaa new-model
aaa authentication login default group tacacs+ local
username admin privilege 15 secret 9 abc
enable secret 9 def
tacacs server T1
 address ipv4 10.0.0.9
ip access-list extended MGMT
 permit tcp any any eq 22
access-list 10 permit 10.0.0.0 0.0.0.255
ip access-group-not-an-acl foo
interface Vlan1
 shutdown
interface Loopback0
 ip address 1.1.1.1 255.255.255.255
line con 0
 logging synchronous
line vty 0 4
 transport input ssh
hostname LAB
"""


def test_interfaces_access_lists_vty_lines_and_authentication_topics() -> None:
    sections = split_sections(LAB_CONFIG)

    assert _headers(select_by_topic(sections, "interfaces")) == [
        "interface Vlan1",
        "interface Loopback0",
    ]
    assert _headers(select_by_topic(sections, "access_lists")) == [
        "ip access-list extended MGMT",
        "access-list 10 permit 10.0.0.0 0.0.0.255",
    ]
    assert _headers(select_by_topic(sections, "vty_lines")) == ["line con 0", "line vty 0 4"]
    assert _headers(select_by_topic(sections, "authentication")) == [
        "aaa new-model",
        "aaa authentication login default group tacacs+ local",
        "username admin privilege 15 secret 9 abc",
        "enable secret 9 def",
        "tacacs server T1",
    ]


def test_regex_and_its_errors() -> None:
    sections = split_sections(CONFIG)

    assert len(select_by_regex(sections, r"^interface Gig.*0/1$")) == 1
    with pytest.raises(ValueError, match="invalid"):
        select_by_regex(sections, "(")
    with pytest.raises(ValueError, match="longer"):
        select_by_regex(sections, "a" * 300)


def test_outline_lists_headers_with_ranges() -> None:
    rows = outline(split_sections(CONFIG))

    assert {"header": "router ospf 100", "lines": "14-16", "line_count": 3} in rows


def test_xr_style_blocks_end_at_the_bang() -> None:
    xr = "router ospf 1\n area 0\n  interface Gi0/0/0/0\n  !\n !\n!\nrouter bgp 1\n !\n"

    ospf = select_by_prefix(split_sections(xr), "router ospf")[0]

    assert "router bgp" not in ospf.text and "interface Gi0/0/0/0" in ospf.text


# -- the tool -----------------------------------------------------------------------------------


class FakeReader:
    def __init__(self, text: str) -> None:
        self.backup = cb.ConfigBackup(text, "backups", "LAB.cfg", "2026-10-30T10:00:00+00:00")

    async def read(self, device, kind, repository):
        return self.backup


def _ctx(text: str, *, content: bool = True) -> ToolContext:
    redactor = Redactor()
    redactor.add_known_secrets(("hunter2hunter2",))
    return ToolContext(
        user_id=7,
        redactor=redactor,
        extras={
            tools.CONFIG_READER_KEY: FakeReader(text),
            RESULT_STORE_KEY: ResultStore(InMemoryResultBackend()),
        },
        sharing=SharingPolicy(inventory=True, content=content),
    )


def _call(ctx: ToolContext, **kwargs):
    tool = next(t for t in tools.build_config_backup_tools() if t.name == "get_config_section")
    return asyncio.run(tool.handler(ctx, tool.input_model(device="LAB", **kwargs)))


BIG = CONFIG + "".join(f"interface Loopback{n}\n description x{n}\n!\n" for n in range(2000))


def test_a_large_config_still_answers_a_section() -> None:
    out = _call(_ctx(BIG), starts_with="router ospf 100")
    data = json.loads(out.content)

    assert len(BIG) > tools.LARGE_CONFIG_CHARS
    assert data["sections_found"] == 1
    assert "router-id 1.1.1.1" in data["sections"][0]["text"]
    assert "handle" not in data and "not_shown" not in data


def test_the_section_text_is_redacted() -> None:
    out = _call(_ctx(CONFIG), topic="bgp")

    assert "hunter2hunter2" not in out.content
    assert "neighbor 10.0.0.2" in out.content


def test_no_selector_returns_the_outline() -> None:
    data = json.loads(_call(_ctx(CONFIG)).content)

    assert data["section_count"] > 5
    assert any(row["header"] == "router bgp 65000" for row in data["outline"])


def test_no_match_says_so() -> None:
    data = json.loads(_call(_ctx(CONFIG), starts_with="router eigrp").content)

    assert data["sections_found"] == 0


def test_an_answer_too_big_for_the_chat_lists_the_rest_and_keeps_a_download() -> None:
    ctx = _ctx(BIG)

    data = json.loads(_call(ctx, starts_with="interface Loopback").content)

    assert data["truncated"] is True
    assert data["not_shown"] and data["handle"].startswith("res_")
    stored = asyncio.run(ctx.extras[RESULT_STORE_KEY].get(7, data["handle"]))
    assert stored.kind == tools.HANDLE_KIND and stored.meta["no_paging"] is True
    assert "Loopback1999" in (stored.text or "")


def test_invalid_regex_is_a_tool_error() -> None:
    out = _call(_ctx(CONFIG), header_regex="(")

    assert out.is_error


def test_needs_the_content_opt_in() -> None:
    out = _call(_ctx(CONFIG, content=False), topic="ospf")

    assert "router-id" not in out.content


def test_only_one_selector_is_allowed() -> None:
    with pytest.raises(ValidationError):
        _call(_ctx(CONFIG), topic="ospf", starts_with="router ospf")
