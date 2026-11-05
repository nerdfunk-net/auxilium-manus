"""Matching neighbours to the inventory, and reconciling sources (doc/AI_TOOL_CHAIN.md §24.11).

Every source is evidence, none is the single source of truth: Nautobot is often incomplete, the
model is as old as its snapshot, the device is current but may have CDP/LLDP switched off. The
reconciliation therefore reports where sources agree and differ, and never reads a missing entry
as a missing link. The inventory lookup is injected, so this module needs no database.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from services.network.interface_names import canonical_interface_name

logger = logging.getLogger(__name__)

MAX_LOOKUPS = 25
_SERIAL_SUFFIX = re.compile(r"\([^)]*\)\s*$")
_IPV4 = re.compile(r"\d{1,3}(\.\d{1,3}){3}")
# A chassis id used as a name (LLDP without a system name): never split at its dots or colons.
_MAC = re.compile(r"([0-9a-f]{4}\.){2}[0-9a-f]{4}|([0-9a-f]{2}[:-]){5}[0-9a-f]{2}")

Record = Mapping[str, Any]


@dataclass(frozen=True)
class Lookup:
    """What an inventory lookup found for one name.

    ``none``: no device has the name. ``ambiguous``: more than one does. ``unknown``: the lookup
    could not be made (no permission, an inventory problem). Only ``match`` names a device.
    """

    status: Literal["match", "none", "ambiguous", "unknown"]
    device: str | None = None


Resolve = Callable[[str], Awaitable[Lookup]]


def candidate_names(raw: str) -> list[str]:
    """Names to try for a CDP/LLDP system name: the full name without a serial, then the host part.

    ``sw2.example.com(FOC1234)`` -> ``sw2.example.com``, ``sw2``. An address is tried as is.
    """
    name = _SERIAL_SUFFIX.sub("", raw).strip().lower()
    if not name:
        return []
    if _IPV4.fullmatch(name) or _MAC.fullmatch(name) or "." not in name:
        return [name]
    return [name, name.split(".", 1)[0]]


async def match_inventory(records: Sequence[Record], resolve: Resolve) -> list[dict[str, Any]]:
    """Copies of ``records`` with an ``inventory`` verdict on every L2 neighbour.

    ``resolve(name)`` answers with a ``Lookup``. Each distinct neighbour is looked up once, at most
    ``MAX_LOOKUPS`` of them; the rest say so. The verdict is ``matched: true`` only for a unique
    device (``how`` says whether the full name or only the host part matched), ``false`` when no
    device has the name, and ``null`` with a note when the lookup was ambiguous, not possible or
    failed: an unclear answer is never reported as a match. An unmatched neighbour is a finding,
    not a fault.
    """
    names: list[str] = []
    for record in records:
        name = str(record.get("neighbor_name") or "")
        if record.get("layer") == "l2" and name and name not in names:
            names.append(name)
    verdicts: dict[str, dict[str, Any]] = {}

    async def look_up(name: str) -> dict[str, Any]:
        for index, candidate in enumerate(candidate_names(name)):
            found = await resolve(candidate)
            if found.status == "match" and found.device:
                verdict: dict[str, Any] = {
                    "matched": True,
                    "device": found.device,
                    "how": "name" if index == 0 else "short_name",
                }
                if index > 0:
                    verdict["note"] = (
                        "matched by the host part of the name only; another device with a "
                        "different domain could be meant"
                    )
                return verdict
            if found.status == "ambiguous":
                return {"matched": None, "note": "more than one inventory device has this name"}
            if found.status == "unknown":
                return {"matched": None, "note": "the inventory could not be searched"}
        return {"matched": False}

    # Sequential: each lookup is a Nautobot request made as the user, and the cap keeps it short.
    for name in names[:MAX_LOOKUPS]:
        try:
            verdicts[name] = await look_up(name)
        except Exception:  # an inventory problem must not hide the neighbours that were found
            logger.warning("Inventory lookup for a neighbour failed", exc_info=True)
            verdicts[name] = {"matched": None, "note": "lookup failed"}
    skipped = {"matched": None, "note": "not looked up (limit)"}
    result: list[dict[str, Any]] = []
    for record in records:
        copy = dict(record)
        name = str(record.get("neighbor_name") or "")
        if record.get("layer") == "l2" and name:
            copy["inventory"] = verdicts.get(name, skipped)
        result.append(copy)
    return result


def _host(name: str) -> str:
    candidates = candidate_names(name)
    return candidates[-1] if candidates else ""


def _label(device: str, interface: str) -> str:
    return f"{device} {interface}".strip()


def _live_label(records: Sequence[Record]) -> str:
    """One label for a port; several records (CDP and LLDP) are listed with their protocol."""
    labels = [
        _label(_host(str(r.get("neighbor_name") or "")), str(r.get("neighbor_interface") or ""))
        for r in records
    ]
    if len(records) == 1:
        return labels[0]
    return "; ".join(
        f"{r.get('protocol')}: {label}" for r, label in zip(records, labels, strict=True)
    )


def _agrees(record: Record, doc_device: str, doc_interface: str) -> bool:
    """Whether a live neighbour names the documented remote device (and interface, if both do)."""
    interface = str(record.get("neighbor_interface") or "")
    same_interface = (
        not interface
        or not doc_interface
        or canonical_interface_name(interface).lower()
        == canonical_interface_name(doc_interface).lower()
    )
    return _host(str(record.get("neighbor_name") or "")) == doc_device and same_interface


def reconcile(
    live: Sequence[Record], documented: Sequence[Record], *, complete: bool = True
) -> dict[str, Any]:
    """Live L2 neighbours against documented cabling, keyed by the local interface.

    A port can have several live records (CDP and LLDP both report it); the port is
    ``confirmed`` when any of them agrees with the documentation, and ``live_sources_differ`` says
    when they name different devices.

    ``confirmed``: a live record names the documented remote device (and interface, when both give
    one). ``conflict``: none does. ``undocumented``: seen live, not documented (a documentation
    gap, not an error). ``not_seen_live``: documented, not seen (link down, CDP/LLDP off, or wrong
    documentation).

    ``complete`` says the documentation was read in full. When it was not, a port that is missing
    from it may simply be on a page that was not read, so such a port is ``not_compared`` instead
    of ``undocumented`` and ``not_seen_live`` is not worked out at all.
    """
    live_by_port: dict[str, list[Record]] = {}
    for record in live:
        if record.get("layer") == "l2" and record.get("local_interface"):
            port = canonical_interface_name(str(record["local_interface"])).lower()
            live_by_port.setdefault(port, []).append(record)
    doc_by_port = {
        canonical_interface_name(str(d.get("local_interface") or "")).lower(): d
        for d in documented
        if d.get("local_interface")
    }
    missing = "undocumented" if complete else "not_compared"
    out: dict[str, list[dict[str, Any]]] = {"confirmed": [], "conflict": [], missing: []}
    if complete:
        out["not_seen_live"] = []
    for port, records in live_by_port.items():
        item: dict[str, Any] = {
            "local_interface": str(records[0].get("local_interface")),
            "live": _live_label(records),
        }
        hosts = {_host(str(r.get("neighbor_name") or "")) for r in records} - {""}
        if len(hosts) > 1:
            item["live_sources_differ"] = True
        doc = doc_by_port.get(port)
        if doc is None:
            out[missing].append(item)
            continue
        doc_device = _host(str(doc.get("remote_device") or ""))
        doc_interface = str(doc.get("remote_interface") or "")
        item["documented"] = _label(doc_device, doc_interface)
        agrees = any(_agrees(r, doc_device, doc_interface) for r in records)
        out["confirmed" if agrees else "conflict"].append(item)
    if complete:
        for port, doc in doc_by_port.items():
            if port not in live_by_port:
                out["not_seen_live"].append(
                    {
                        "local_interface": str(doc.get("local_interface")),
                        "documented": _label(
                            _host(str(doc.get("remote_device") or "")),
                            str(doc.get("remote_interface") or ""),
                        ),
                    }
                )
    return {**out, "complete": complete, "counts": {key: len(items) for key, items in out.items()}}


def documented_from_interfaces(answer: Mapping[str, Any]) -> list[dict[str, str]]:
    """Documented far ends from a ``list_interfaces`` answer (those with ``connected_to``)."""
    documented: list[dict[str, str]] = []
    for item in answer.get("items") or []:
        far = item.get("connected_to") if isinstance(item, Mapping) else None
        if isinstance(far, Mapping) and far.get("device"):
            documented.append(
                {
                    "local_interface": str(item.get("name") or ""),
                    "remote_device": str(far.get("device")),
                    "remote_interface": str(far.get("interface") or ""),
                }
            )
    return documented
