"""What changed between two BGP readings. Pure functions (doc/plans/BGP_PLAYBOOK.md step 4).

Two inputs, two levels:

* ``compare_records``: the merged records of ``bgp_records.summarize_bgp`` (one per VRF, neighbour
  and address family). Fast, no pyATS. The headline of a comparison.
* ``MODEL_NOISE_KEYS``: keys of Genie's learned ``info`` tree to leave out when the whole model is
  diffed (``compare_bgp_learns(detail=True)``).

Counters, timers and uptimes change on every read, so they never count as a change. State, the
neighbour set, session settings, the reset reason and the number of times a session dropped do: a
session that flapped between two readings shows as ``times_dropped`` going up.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

Record = Mapping[str, Any]
Change = dict[str, Any]

# Fields of a record that are compared. ``up_down`` and the message counts are left out (they move
# on every read); so is ``last_reset``, which is the time *since* the reset and so also moves.
COMPARED_FIELDS: tuple[str, ...] = (
    "remote_as",
    "type",
    "state",
    "session_state",
    "prefixes_received",
    "shutdown",
    "description",
    "peer_group",
    "neighbor_router_id",
    "hold_time",
    "keepalive",
    "reset_reason",
    "times_established",
    "times_dropped",
)

# Keys of Genie's learned BGP model that are noise. Genie's own ``_exclude`` for BGP also lists keys
# that carry findings (``state_pfxrcd``, ``last_reset``, ``reset_reason``, ``hold_time``,
# ``router_id``, ``connections_dropped``/``connections_established``, ``prefixes``); those are NOT
# here, so a session that went down or flapped is still reported. The shim ignores the snapshot's
# own list on purpose (``pyats-shim/app/diff.py``), so these go to it as the caller's ``exclude``.
MODEL_NOISE_KEYS: tuple[str, ...] = (
    "if_handle",
    "keepalives",
    "foreign_port",
    "local_port",
    "msg_rcvd",
    "msg_sent",
    "up_down",
    "up_time",
    "down_time",
    "last_read",
    "last_write",
    "current_time",
    "last_reset",
    "bgp_table_version",
    "routing_table_version",
    "tbl_ver",
    "table_version",
    "neighbor_version",
    "memory_usage",
    "total_memory",
    "updates",
    "mss",
    "total",
    "total_bytes",
    "sent",
    "received",
    "status_codes",
)

MAX_CHANGES = 500


def _key(record: Record) -> tuple[str, str, str]:
    return (str(record.get("vrf")), str(record.get("neighbor")), str(record.get("address_family")))


def _row(record_key: tuple[str, str, str], change: str, **extra: Any) -> Change:
    vrf, neighbor, family = record_key
    return {
        "vrf": vrf,
        "neighbor": neighbor,
        "address_family": None if family == "None" else family,
        "change": change,
        "field": None,
        "before": None,
        "after": None,
        **extra,
    }


def compare_records(before: Sequence[Record], after: Sequence[Record]) -> list[Change]:
    """One row per added or removed neighbour/address family and per changed field, sorted."""
    old = {_key(r): r for r in before}
    new = {_key(r): r for r in after}
    changes: list[Change] = []
    for record_key in sorted(old.keys() | new.keys()):
        if record_key not in new:
            changes.append(_row(record_key, "removed", before=old[record_key].get("state")))
        elif record_key not in old:
            changes.append(_row(record_key, "added", after=new[record_key].get("state")))
        else:
            for field in COMPARED_FIELDS:
                was, now = old[record_key].get(field), new[record_key].get(field)
                if was != now:
                    changes.append(_row(record_key, "changed", field=field, before=was, after=now))
    return changes


def compare_facts(before: Mapping[str, Any], after: Mapping[str, Any]) -> list[Change]:
    """Changes of the global facts (local AS, router ids), as rows without a neighbour."""
    changes: list[Change] = []
    for field in ("local_as", "router_ids"):
        was, now = before.get(field), after.get(field)
        if was != now:
            changes.append(_row(("", "", "None"), "changed", field=field, before=was, after=now))
    return changes


def summarize_changes(changes: Sequence[Change]) -> dict[str, int]:
    """Counts for the answer's first line."""
    return {
        "added": sum(c["change"] == "added" for c in changes),
        "removed": sum(c["change"] == "removed" for c in changes),
        "changed_fields": sum(c["change"] == "changed" for c in changes),
        "state_changes": sum(c["change"] == "changed" and c["field"] == "state" for c in changes),
    }
