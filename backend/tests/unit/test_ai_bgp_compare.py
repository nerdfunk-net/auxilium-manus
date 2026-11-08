"""What changed between two BGP readings (doc/plans/BGP_PLAYBOOK.md step 4)."""

from __future__ import annotations

from typing import Any

from services.ai_assistant.learn import bgp_compare as bc


def _rec(neighbor: str = "10.0.0.1", family: str = "ipv4 unicast", **fields: Any) -> dict[str, Any]:
    base = {
        "vrf": "default",
        "neighbor": neighbor,
        "address_family": family,
        "remote_as": "65000",
        "type": "internal",
        "state": "Established",
        "session_state": "established",
        "prefixes_received": 1,
        "shutdown": False,
        "description": None,
        "peer_group": None,
        "neighbor_router_id": "10.0.0.1",
        "hold_time": 180,
        "keepalive": 60,
        "reset_reason": None,
        "times_established": 1,
        "times_dropped": 0,
        "up_down": "00:10:00",
        "messages_received": 10,
        "messages_sent": 11,
        "last_reset": "never",
    }
    return {**base, **fields}


def test_identical_readings_have_no_changes() -> None:
    assert bc.compare_records([_rec()], [_rec()]) == []


def test_counters_timers_and_the_age_of_the_last_reset_are_not_changes() -> None:
    later = _rec(
        up_down="05:00:00", messages_received=900, messages_sent=950, last_reset="01:00:00"
    )

    assert bc.compare_records([_rec()], [later]) == []


def test_a_session_that_went_down_is_a_state_change_with_both_values() -> None:
    down = _rec(state="Active", prefixes_received=None, session_state="active")

    changes = bc.compare_records([_rec()], [down])

    fields = {c["field"]: (c["before"], c["after"]) for c in changes}
    assert fields["state"] == ("Established", "Active")
    assert fields["prefixes_received"] == (1, None)
    assert all(c["change"] == "changed" and c["neighbor"] == "10.0.0.1" for c in changes)
    assert bc.summarize_changes(changes)["state_changes"] == 1


def test_a_flap_between_readings_shows_in_the_drop_counter_and_reason() -> None:
    flapped = _rec(times_established=2, times_dropped=1, reset_reason="Peer closed the session")

    changes = bc.compare_records([_rec()], [flapped])

    assert {c["field"] for c in changes} == {"times_established", "times_dropped", "reset_reason"}


def test_added_and_removed_neighbors_and_families() -> None:
    before = [_rec("10.0.0.1"), _rec("10.0.0.2")]
    after = [_rec("10.0.0.1"), _rec("10.0.0.1", "vpnv4 unicast", state=None), _rec("10.0.0.3")]

    changes = bc.compare_records(before, after)

    assert [(c["neighbor"], c["address_family"], c["change"]) for c in changes] == [
        ("10.0.0.1", "vpnv4 unicast", "added"),
        ("10.0.0.2", "ipv4 unicast", "removed"),
        ("10.0.0.3", "ipv4 unicast", "added"),
    ]
    assert bc.summarize_changes(changes) == {
        "added": 2,
        "removed": 1,
        "changed_fields": 0,
        "state_changes": 0,
    }


def test_the_same_neighbor_in_two_vrfs_is_not_mixed_up() -> None:
    before = [_rec(vrf="BLUE"), _rec(vrf="RED")]
    after = [_rec(vrf="BLUE"), _rec(vrf="RED", state="Idle")]

    changes = bc.compare_records(before, after)

    assert [(c["vrf"], c["field"]) for c in changes] == [("RED", "state")]


def test_global_facts_changes_are_rows_without_a_neighbor() -> None:
    changes = bc.compare_facts(
        {"local_as": "65000", "router_ids": ["1.1.1.1"]},
        {"local_as": "65001", "router_ids": ["1.1.1.1"]},
    )

    assert [(c["field"], c["before"], c["after"], c["neighbor"]) for c in changes] == [
        ("local_as", "65000", "65001", "")
    ]
    assert bc.compare_facts({"local_as": "1"}, {"local_as": "1"}) == []


def test_noise_keys_leave_out_flap_and_state_evidence() -> None:
    kept = {"state_pfxrcd", "last_reset", "reset_reason", "hold_time", "router_id"}
    kept |= {"connections_dropped", "connections_established", "prefixes", "session_state"}

    assert not kept & set(bc.MODEL_NOISE_KEYS) - {"last_reset"}
    # ``last_reset`` is the age of the last reset in the model too, so it is noise there.
    assert "last_reset" in bc.MODEL_NOISE_KEYS
    assert {"msg_rcvd", "msg_sent", "up_time", "up_down"} <= set(bc.MODEL_NOISE_KEYS)
