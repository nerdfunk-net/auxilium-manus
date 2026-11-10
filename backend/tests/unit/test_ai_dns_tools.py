"""``get_dns_lookup``: forward and reverse DNS for Ask the Net (doc/AI_TOOL_CHAIN.md §50)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from services.ai_assistant.data_sharing import SharingPolicy
from services.ai_assistant.dns_resolver import DnsAnswer
from services.ai_assistant.providers.base import ToolCall
from services.ai_assistant.redaction import Redactor
from services.ai_assistant.tools.base import Toolbox, ToolContext, ToolOutput
from services.ai_assistant.tools.dns_tools import DNS_RESOLVER_KEY, build_dns_tools
from services.ai_assistant.tools.playbook_tools import known_general_tool_names

ALL = SharingPolicy(inventory=True, addresses=True)


class FakeResolver:
    allowed_suffixes = ("local.zz",)

    def __init__(self, forward: DnsAnswer | None = None, reverse: DnsAnswer | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._forward = forward or DnsAnswer("found", ("10.0.0.7",), "lab.local.zz")
        self._reverse = reverse or DnsAnswer("found", ("lab.local.zz",), None)

    async def forward(self, name: str) -> DnsAnswer:
        self.calls.append(("forward", name))
        return self._forward

    async def reverse(self, address: str) -> DnsAnswer:
        self.calls.append(("reverse", address))
        return self._reverse


def _call(resolver: FakeResolver, sharing: SharingPolicy = ALL, **args: Any) -> ToolOutput:
    ctx = ToolContext(
        user_id=1, redactor=Redactor(), extras={DNS_RESOLVER_KEY: resolver}, sharing=sharing
    )
    box = Toolbox(build_dns_tools(), ctx)
    return asyncio.run(box.execute(ToolCall(id="1", name="get_dns_lookup", input=args)))


def _json(out: ToolOutput) -> dict[str, Any]:
    assert not out.is_error, out.content
    return json.loads(out.content)


def test_the_tool_is_one_read_and_known_to_the_playbooks() -> None:
    assert [t.name for t in build_dns_tools()] == ["get_dns_lookup"]
    assert "get_dns_lookup" in known_general_tool_names()


def test_a_name_is_resolved_forward() -> None:
    resolver = FakeResolver()
    data = _json(_call(resolver, query="LAB.local.zz"))

    assert resolver.calls == [("forward", "lab.local.zz")]
    assert data["kind"] == "forward"
    assert data["status"] == "found"
    assert data["addresses"] == ["10.0.0.7"]
    assert data["canonical_name"] == "lab.local.zz"
    assert "system resolver" in data["resolver"]
    assert "not stored" in data["note"] or "live" in data["note"]


def test_an_address_is_resolved_in_reverse() -> None:
    resolver = FakeResolver()
    data = _json(_call(resolver, query="10.0.0.7"))

    assert resolver.calls == [("reverse", "10.0.0.7")]
    assert data["kind"] == "reverse"
    assert data["names"] == ["lab.local.zz"]


def test_an_ipv6_address_is_normalised_before_the_reverse_lookup() -> None:
    resolver = FakeResolver()
    _json(_call(resolver, query="2001:DB8:0:0:0:0:0:1"))
    assert resolver.calls == [("reverse", "2001:db8::1")]


def test_not_found_is_a_status_with_a_caution_not_an_error() -> None:
    resolver = FakeResolver(forward=DnsAnswer("not_found", (), None))
    data = _json(_call(resolver, query="nope.local.zz"))
    assert data["status"] == "not_found"
    assert "does not exist" in data["note"]  # the note tells the model not to claim it


def test_an_unavailable_resolver_is_reported() -> None:
    resolver = FakeResolver(reverse=DnsAnswer("unavailable", (), None))
    assert _json(_call(resolver, query="10.0.0.7"))["status"] == "unavailable"


def test_a_name_outside_the_suffixes_is_refused_without_a_lookup() -> None:
    resolver = FakeResolver()
    data = _json(_call(resolver, query="secret.attacker.com"))
    assert resolver.calls == []
    assert data["status"] == "not_allowed"
    assert "local.zz" in data["message"]


def test_a_special_address_is_refused_without_a_lookup() -> None:
    resolver = FakeResolver()
    data = _json(_call(resolver, query="169.254.169.254"))
    assert resolver.calls == []
    assert data["status"] == "not_allowed"


def test_the_data_switches_are_checked_before_any_lookup() -> None:
    for sharing in (SharingPolicy(), SharingPolicy(inventory=True), SharingPolicy(addresses=True)):
        resolver = FakeResolver()
        out = _call(resolver, sharing, query="lab.local.zz")
        assert resolver.calls == []
        assert "not_shared" in out.content


def test_an_empty_or_oversized_query_is_invalid_input() -> None:
    resolver = FakeResolver()
    assert _call(resolver, query="").is_error
    assert _call(resolver, query="a" * 300).is_error
    assert _call(resolver, query="lab.local.zz", extra="x").is_error
    assert resolver.calls == []


def test_a_resolver_failure_is_contained_by_the_choke_point() -> None:
    class Boom(FakeResolver):
        async def forward(self, name: str) -> DnsAnswer:
            raise RuntimeError("secret internals")

    out = _call(Boom(), query="lab.local.zz")
    assert out.is_error
    assert "secret internals" not in out.content


def test_a_known_secret_in_an_answer_is_redacted() -> None:
    resolver = FakeResolver(reverse=DnsAnswer("found", ("hunter2-host.local.zz",), None))
    redactor = Redactor()
    redactor.add_known_secrets(["hunter2-host"])
    ctx = ToolContext(
        user_id=1, redactor=redactor, extras={DNS_RESOLVER_KEY: resolver}, sharing=ALL
    )
    out = asyncio.run(
        Toolbox(build_dns_tools(), ctx).execute(
            ToolCall(id="1", name="get_dns_lookup", input={"query": "10.0.0.7"})
        )
    )
    assert "hunter2-host" not in out.content


def _session(resolver: FakeResolver | None, may_query_batfish: bool = True) -> Any:
    from services.ai_assistant.surfaces import build_general_session
    from tests.unit.test_ai_batfish_tools import FakeReader

    return build_general_session(
        user_id=1,
        reader=FakeReader(),
        store=None,
        sharing=ALL,
        may_query_batfish=may_query_batfish,
        dns_resolver=resolver,
    )


def test_the_general_surface_offers_the_tool_only_with_a_resolver() -> None:
    assert "get_dns_lookup" not in [s.name for s in _session(None).toolbox.specs()]
    offered = _session(FakeResolver())
    assert "get_dns_lookup" in [s.name for s in offered.toolbox.specs()]
    assert "get_dns_lookup" in offered.system


def test_a_user_without_batfish_still_gets_the_dns_tool_and_the_prompt_says_so() -> None:
    session = _session(FakeResolver(), may_query_batfish=False)
    assert [s.name for s in session.toolbox.specs()] == ["get_dns_lookup"]
    assert "DNS" in session.system.split("only the")[-1]
