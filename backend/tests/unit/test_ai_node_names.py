"""Matching a device name as the user or Nautobot writes it to a Batfish node name.

Batfish names a node after the hostname in its config (lower case, usually without a domain);
Nautobot names the same device ``LAB.local.zz``. Pure functions, no I/O.
"""

from __future__ import annotations

from services.ai_assistant.node_names import NodeNameCache, resolve_node_names

KNOWN = ["lab", "r1", "sw-core.corp.zz", "sw-edge"]


def test_fqdn_resolves_to_the_short_batfish_node() -> None:
    result = resolve_node_names(["LAB.local.zz"], KNOWN)

    assert result.resolved == {"LAB.local.zz": "lab"}
    assert not result.unknown and not result.ambiguous


def test_short_name_resolves_to_a_node_that_carries_the_domain() -> None:
    result = resolve_node_names(["sw-core"], KNOWN)

    assert result.resolved == {"sw-core": "sw-core.corp.zz"}


def test_a_different_domain_is_not_the_same_device() -> None:
    result = resolve_node_names(["sw-core.other.zz"], KNOWN)

    assert result.resolved == {}
    assert "sw-core.other.zz" in result.unknown


def test_exact_match_is_case_insensitive_and_wins_over_a_domain_match() -> None:
    result = resolve_node_names(["LAB", "Sw-Edge"], ["lab", "lab.x.zz", "sw-edge"])

    assert result.resolved == {"LAB": "lab", "Sw-Edge": "sw-edge"}


def test_a_short_name_matching_two_domains_is_ambiguous_not_guessed() -> None:
    result = resolve_node_names(["lab"], ["lab.a.zz", "lab.b.zz"])

    assert result.resolved == {}
    assert result.ambiguous == {"lab": ("lab.a.zz", "lab.b.zz")}


def test_unknown_names_come_with_close_suggestions() -> None:
    result = resolve_node_names(["sw-cor"], KNOWN)

    assert result.unknown == {"sw-cor": ("sw-core.corp.zz",)}


def test_unknown_name_without_a_close_match_has_no_suggestions() -> None:
    assert resolve_node_names(["zzz"], KNOWN).unknown == {"zzz": ()}


def test_a_label_that_only_occurs_inside_another_hostname_is_not_suggested() -> None:
    assert resolve_node_names(["core"], KNOWN).unknown == {"core": ()}
    assert resolve_node_names(["edge"], KNOWN).unknown == {"edge": ()}


def test_suggestions_are_completions_or_near_misses_of_the_first_label() -> None:
    result = resolve_node_names(["sw"], KNOWN)
    assert result.unknown == {"sw": ("sw-core.corp.zz", "sw-edge")}

    assert resolve_node_names(["sw-egde"], KNOWN).unknown == {"sw-egde": ("sw-edge",)}
    typo = resolve_node_names(["sw-edge.x.zz"], ["sw-edgy"])
    assert typo.unknown == {"sw-edge.x.zz": ("sw-edgy",)}


def test_several_names_are_resolved_independently() -> None:
    result = resolve_node_names(["lab.local.zz", "r1", "nope"], KNOWN)

    assert result.resolved == {"lab.local.zz": "lab", "r1": "r1"}
    assert list(result.unknown) == ["nope"]


def test_changed_lists_only_the_names_that_were_rewritten() -> None:
    result = resolve_node_names(["lab.local.zz", "r1", "R1"], KNOWN)

    assert result.changed == {"lab.local.zz": "lab", "R1": "r1"}


def test_whitespace_is_ignored_and_an_empty_snapshot_resolves_nothing() -> None:
    assert resolve_node_names([" lab.local.zz "], KNOWN).resolved == {" lab.local.zz ": "lab"}
    assert resolve_node_names(["lab"], []).resolved == {}


class _Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def test_cache_returns_what_was_stored_until_it_expires() -> None:
    clock = _Clock()
    cache = NodeNameCache(ttl_seconds=60, max_entries=8, clock=clock)
    cache.put(("h", 1, "net", "snap"), ("a", "b"))

    assert cache.get(("h", 1, "net", "snap")) == ("a", "b")
    clock.now += 61
    assert cache.get(("h", 1, "net", "snap")) is None


def test_cache_drops_the_oldest_entry_when_full_and_can_be_cleared() -> None:
    clock = _Clock()
    cache = NodeNameCache(ttl_seconds=60, max_entries=2, clock=clock)
    for n in range(3):
        clock.now += 1
        cache.put(("h", 1, "net", f"s{n}"), (f"n{n}",))

    assert cache.get(("h", 1, "net", "s0")) is None
    assert cache.get(("h", 1, "net", "s2")) == ("n2",)
    cache.clear()
    assert cache.get(("h", 1, "net", "s2")) is None
