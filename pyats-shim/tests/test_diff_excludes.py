"""Merging the snapshots' own `_exclude` lists into a diff (no genie needed)."""

from __future__ import annotations

from app.diff import SNAPSHOT_NOISE_KEYS, _snapshot_excludes, merged_excludes, snapshot_excludes

OSPF = {
    "info": {"vrf": {}},
    "_exclude": ["age", "seq", "state", "lsas", "dr_router_id", "statistics", "dead_timer"],
}


def test_snapshot_excludes_reads_the_list() -> None:
    assert _snapshot_excludes({"_exclude": ["age", "seq"]}) == ["age", "seq"]


def test_snapshot_excludes_ignores_missing_or_malformed_values() -> None:
    assert _snapshot_excludes({"info": {}}) == []
    assert _snapshot_excludes({"_exclude": "age"}) == []
    assert _snapshot_excludes(None) == []
    assert _snapshot_excludes({"_exclude": ["age", " ", 5]}) == ["age", "5"]


def test_snapshot_excludes_is_capped() -> None:
    assert len(_snapshot_excludes({"_exclude": [f"k{i}" for i in range(1000)]})) == 200


def test_only_noise_keys_are_applied_and_the_rest_stays_compared() -> None:
    applied, kept = snapshot_excludes(OSPF, OSPF)

    assert applied == ["age", "seq", "dead_timer"]
    assert kept == ["state", "lsas", "dr_router_id", "statistics"]
    assert not set(kept) & SNAPSHOT_NOISE_KEYS


def test_a_reference_cannot_switch_off_a_real_field() -> None:
    reference = {"info": {}, "_exclude": ["router_id", "cost", "neighbors"]}

    assert merged_excludes(OSPF, reference) == ["age", "seq", "dead_timer"]
    assert snapshot_excludes(OSPF, reference)[1][-3:] == ["router_id", "cost", "neighbors"]


def test_caller_keys_are_applied_even_when_not_noise() -> None:
    assert merged_excludes(OSPF, OSPF, exclude=["state"]) == ["state", "age", "seq", "dead_timer"]


def test_merge_puts_caller_keys_first_and_drops_duplicates() -> None:
    other = {"_exclude": ["seq", "uptime"]}

    merged = merged_excludes(OSPF, other, exclude=["updated", "age"])

    assert merged == ["updated", "age", "seq", "dead_timer", "uptime"]


def test_merge_can_be_switched_off() -> None:
    assert merged_excludes(OSPF, OSPF, exclude=["x"], use_snapshot_excludes=False) == ["x"]
    assert merged_excludes(OSPF, OSPF, use_snapshot_excludes=False) == []


def test_merge_without_any_list_is_empty() -> None:
    assert merged_excludes({"a": 1}, {"a": 2}) == []
