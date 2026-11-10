"""Anonymous shape profile of the client data, and synthetic data generated from one.

``export_profile`` reads (SELECT only) how the client data tables are *shaped*: rows per device,
how many devices see the same MAC, how many ARP MACs also sit in a MAC table, retained sessions,
and the PostgreSQL settings that steer the planner. It holds counts and distributions only: no
device name, address, MAC, port or hostname leaves the system (devices become ``dev001`` ...).

``synthesize`` builds invented rows with that shape in an *empty* database, so a query plan
can be studied in a lab with the production shape and none of its data. Used by
``analyze_client_tool.py`` (sub-commands ``export`` and ``synth``).
"""

from __future__ import annotations

import random
import uuid
from collections import defaultdict
from collections.abc import Iterator, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, insert, intersect, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from core.models.base import Base
from core.models.client_data import (
    ClientDataCollection,
    ClientHostname,
    ClientIpAddress,
    ClientMacAddress,
    ClientPortNeighbor,
)
from repositories.client_data_query_repository import _latest_collections

PROFILE_VERSION = 1
_MODELS: tuple[Any, ...] = (
    ClientDataCollection,
    ClientIpAddress,
    ClientMacAddress,
    ClientHostname,
    ClientPortNeighbor,
)
_PLANNER_SETTINGS = (
    "server_version",
    "work_mem",
    "jit",
    "join_collapse_limit",
    "from_collapse_limit",
    "max_parallel_workers_per_gather",
    "random_page_cost",
    "effective_cache_size",
    "default_statistics_target",
)
_BATCH = 20_000
_MAC_MULTIPLIER = 2654435761  # odd, so id -> MAC is a bijection modulo 2**48


# -- export ------------------------------------------------------------------------------------


def _joined(model: Any, table: str) -> Any:
    latest = _latest_collections(table)
    return and_(
        model.session_id == latest.c.session_id, model.device_name == latest.c.device_name
    ), latest


def _per_device(db: Session) -> dict[str, dict[str, Any]]:
    """Current rows per device and table (the newest collection that read each table)."""
    devices: dict[str, dict[str, Any]] = defaultdict(dict)
    mac, ip, hostname, neighbor = (
        ClientMacAddress,
        ClientIpAddress,
        ClientHostname,
        ClientPortNeighbor,
    )
    on, latest = _joined(mac, "mac")
    for row in db.execute(
        select(
            mac.device_name,
            func.count(),
            func.count(func.distinct(mac.mac_address)),
            func.count(func.distinct(mac.vlan)),
            func.count(func.distinct(mac.port)),
            func.count().filter(mac.vlan.is_(None)),
        )
        .join(latest, on)
        .group_by(mac.device_name)
    ):
        devices[row[0]]["mac"] = {
            "rows": row[1],
            "distinct_macs": row[2],
            "distinct_vlans": row[3],
            "distinct_ports": row[4],
            "rows_without_vlan": row[5],
        }
    on, latest = _joined(ip, "arp")
    for row in db.execute(
        select(
            ip.device_name,
            func.count(),
            func.count(func.distinct(ip.mac_address)),
            func.count().filter(ip.mac_address.is_(None)),
            func.count(func.distinct(ip.ip_address)),
            func.count(func.distinct(ip.vrf)),
            func.count().filter(ip.vrf.is_not(None)),
            func.count(func.distinct(ip.vlan)),
            func.count().filter(ip.vlan.is_not(None)),
        )
        .join(latest, on)
        .group_by(ip.device_name)
    ):
        devices[row[0]]["arp"] = {
            "rows": row[1],
            "distinct_macs": row[2],
            "rows_without_mac": row[3],
            "distinct_ips": row[4],
            "distinct_vrfs": row[5],
            "rows_with_vrf": row[6],
            "distinct_vlans": row[7],
            "rows_with_vlan": row[8],
        }
    on, latest = _joined(hostname, "arp")
    for row in db.execute(
        select(hostname.device_name, func.count()).join(latest, on).group_by(hostname.device_name)
    ):
        devices[row[0]]["hostnames"] = row[1]
    on, latest = _joined(neighbor, "neighbor")
    for row in db.execute(
        select(
            neighbor.device_name,
            func.count(),
            func.count().filter(neighbor.is_infrastructure.is_(True)),
            func.count().filter(neighbor.channel.is_not(None)),
        )
        .join(latest, on)
        .group_by(neighbor.device_name)
    ):
        devices[row[0]]["neighbors"] = {
            "rows": row[1],
            "infrastructure": row[2],
            "in_channel": row[3],
        }
    return devices


def _collections(db: Session) -> dict[str, dict[str, Any]]:
    """Retained sessions and the newest statuses per device (a small table: read in full)."""
    c = ClientDataCollection
    newest: dict[str, tuple[datetime, Any]] = {}
    sessions: dict[str, int] = defaultdict(int)
    for row in db.execute(
        select(c.device_name, c.collected_at, c.arp_status, c.mac_status, c.neighbor_status)
    ):
        sessions[row.device_name] += 1
        if row.device_name not in newest or row.collected_at > newest[row.device_name][0]:
            newest[row.device_name] = (row.collected_at, row)
    return {
        name: {
            "sessions": sessions[name],
            "arp_status": row.arp_status,
            "mac_status": row.mac_status,
            "neighbor_status": row.neighbor_status,
        }
        for name, (_, row) in newest.items()
    }


def _histogram(db: Session, grouped: Any) -> dict[str, int]:
    """``{n: how many groups have n members}`` for a ``select(count(...)).group_by(...)``."""
    sub = grouped.subquery()
    result = db.execute(select(sub.c[0], func.count()).group_by(sub.c[0]).order_by(sub.c[0]))
    return {str(n): count for n, count in result}


def _global_shape(db: Session) -> dict[str, Any]:
    mac, ip = ClientMacAddress, ClientIpAddress
    mac_on, mac_latest = _joined(mac, "mac")
    ip_on, ip_latest = _joined(ip, "arp")
    mac_cur = select(mac.mac_address).join(mac_latest, mac_on).distinct()
    arp_cur = select(ip.mac_address).join(ip_latest, ip_on).where(ip.mac_address.is_not(None))
    overlap = select(func.count()).select_from(intersect(mac_cur, arp_cur.distinct()).subquery())
    return {
        "distinct_macs_in_mac_tables": db.execute(
            select(func.count()).select_from(mac_cur.subquery())
        ).scalar(),
        "distinct_macs_in_arp": db.execute(
            select(func.count()).select_from(arp_cur.distinct().subquery())
        ).scalar(),
        "macs_in_both": db.execute(overlap).scalar(),
        "devices_per_mac": _histogram(
            db,
            select(func.count(func.distinct(mac.device_name)))
            .join(mac_latest, mac_on)
            .group_by(mac.mac_address),
        ),
        "ips_per_arp_mac": _histogram(
            db,
            select(func.count(func.distinct(ip.ip_address)))
            .join(ip_latest, ip_on)
            .where(ip.mac_address.is_not(None))
            .group_by(ip.mac_address),
        ),
        "total_rows_all_sessions": {
            model.__tablename__: db.execute(select(func.count()).select_from(model)).scalar()
            for model in _MODELS
        },
    }


def _planner(db: Session) -> dict[str, str]:
    return {
        name: str(db.execute(select(func.current_setting(name))).scalar())
        for name in _PLANNER_SETTINGS
    }


def export_profile(engine: Engine) -> dict[str, Any]:
    """The anonymous profile (see the module doc). Read-only."""
    with Session(engine) as db:
        db.connection().exec_driver_sql("SET TRANSACTION READ ONLY")
        per_device = _per_device(db)
        collections = _collections(db)
        names = sorted(
            set(per_device) | set(collections),
            key=lambda n: (
                -(
                    per_device.get(n, {}).get("arp", {}).get("rows", 0)
                    + per_device.get(n, {}).get("mac", {}).get("rows", 0)
                ),
                n,
            ),
        )
        devices = [
            {"id": f"dev{index:03d}", **per_device.get(name, {}), **collections.get(name, {})}
            for index, name in enumerate(names, start=1)
        ]
        return {
            "profile_version": PROFILE_VERSION,
            "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "devices": devices,
            "global": _global_shape(db),
            "planner": _planner(db),
        }


# -- synthesize --------------------------------------------------------------------------------


def _mac(index: int) -> str:
    digits = f"{(index * _MAC_MULTIPLIER) % 16**12:012x}"
    return f"{digits[0:4]}.{digits[4:8]}.{digits[8:12]}"


def _ip(index: int) -> str:
    return f"10.{(index >> 16) & 255}.{(index >> 8) & 255}.{index & 255 or 1}"


def _deal(remaining: list[int], count: int, fresh: Iterator[int]) -> list[int]:
    """*count* distinct MAC ids from the shared slots (a MAC seen by several devices is several
    slots), topped up with fresh ids if the slots run out."""
    chosen: list[int] = []
    seen: set[int] = set()
    skipped: list[int] = []
    while remaining and len(chosen) < count:
        item = remaining.pop()
        if item in seen:
            skipped.append(item)
            continue
        seen.add(item)
        chosen.append(item)
    remaining.extend(skipped)
    while len(chosen) < count:
        chosen.append(next(fresh))
    return chosen


def _mac_slots(shape: dict[str, Any], rng: random.Random) -> list[int]:
    """One slot per (MAC, device) pair: a MAC seen by n devices appears n times."""
    slots: list[int] = []
    next_id = 0
    for devices_seen, macs in shape["devices_per_mac"].items():
        for _ in range(int(macs)):
            slots.extend([next_id] * int(devices_seen))
            next_id += 1
    rng.shuffle(slots)
    return slots


def _device_rows(
    device: dict[str, Any],
    mac_ids: list[int],
    arp_mac_ids: list[int],
    rng: random.Random,
    ip_start: int,
) -> dict[str, list[dict[str, Any]]]:
    """The rows of one collection of one device (without session id and time)."""
    out: dict[str, list[dict[str, Any]]] = {"mac": [], "arp": [], "host": [], "nb": []}
    name = device["id"]
    if mac := device.get("mac"):
        vlans = [str(10 * (1 + i)) for i in range(max(mac["distinct_vlans"], 1))]
        ports = [f"Gi1/0/{1 + i}" for i in range(max(mac["distinct_ports"], 1))]
        for i in range(mac["rows"]):
            mac_id = mac_ids[i % len(mac_ids)] if mac_ids else i
            out["mac"].append(
                {
                    "mac_address": _mac(mac_id),
                    "vlan": None if i < mac["rows_without_vlan"] else rng.choice(vlans),
                    "port": rng.choice(ports),
                    "device_name": name,
                }
            )
    if arp := device.get("arp"):
        ip_count = max(arp["distinct_ips"], 1)
        vrfs = [f"vrf{i}" for i in range(arp["distinct_vrfs"])]
        vlans = [str(10 * (1 + i)) for i in range(max(arp["distinct_vlans"], 1))]
        for i in range(arp["rows"]):
            has_mac = i >= arp["rows_without_mac"] and bool(arp_mac_ids)
            vlan = rng.choice(vlans) if i < arp["rows_with_vlan"] else None
            out["arp"].append(
                {
                    "ip_address": _ip(ip_start + i % ip_count),
                    "mac_address": _mac(arp_mac_ids[i % len(arp_mac_ids)]) if has_mac else None,
                    "interface": f"Vlan{vlan}" if vlan else "Gi0/0/0",
                    "vrf": rng.choice(vrfs) if vrfs and i < arp["rows_with_vrf"] else None,
                    "vlan": vlan,
                    "device_name": name,
                }
            )
        for ip in sorted({row["ip_address"] for row in out["arp"]})[: device.get("hostnames", 0)]:
            out["host"].append(
                {
                    "ip_address": ip,
                    "hostname": f"h-{ip.replace('.', '-')}.example.net",
                    "device_name": name,
                }
            )
    if nb := device.get("neighbors"):
        for i in range(nb["rows"]):
            infra = i < nb["infrastructure"]
            out["nb"].append(
                {
                    "port": f"Gi1/0/{1 + i}",
                    "channel": "Po1" if i < nb["in_channel"] else None,
                    "neighbor_name": f"neighbor{i}",
                    "neighbor_port": "Gi0/1",
                    "protocol": "lldp",
                    "capabilities": "bridge" if infra else "station",
                    "is_infrastructure": infra,
                    "device_name": name,
                }
            )
    return out


def _batches(rows: Sequence[dict[str, Any]]) -> Iterator[Sequence[dict[str, Any]]]:
    for start in range(0, len(rows), _BATCH):
        yield rows[start : start + _BATCH]


def table_row_counts(engine: Engine) -> dict[str, int]:
    with Session(engine) as db:
        return {
            model.__tablename__: db.execute(select(func.count()).select_from(model)).scalar() or 0
            for model in _MODELS
        }


def synthesize(engine: Engine, profile: dict[str, Any], seed: int = 1) -> dict[str, int]:
    """Write invented rows with the profile's shape. The target tables must be empty."""
    if profile.get("profile_version") != PROFILE_VERSION:
        raise ValueError(f"unsupported profile version {profile.get('profile_version')!r}")
    Base.metadata.create_all(engine, tables=[model.__table__ for model in _MODELS])
    if any(table_row_counts(engine).values()):
        raise ValueError("the target client_* tables are not empty: use a scratch database")
    rng = random.Random(seed)  # noqa: S311 - a reproducible shape, not a secret
    devices = profile["devices"]
    shape = profile["global"]
    slots = _mac_slots(shape, rng)
    fresh = iter(range(10_000_000, 99_000_000))
    pool_size = max(int(shape["distinct_macs_in_mac_tables"]), 1)
    arp_in_pool = int(shape["macs_in_both"]) / max(int(shape["distinct_macs_in_arp"]), 1)
    max_sessions = max((int(d.get("sessions", 1)) for d in devices), default=1)
    now = datetime.now(UTC)
    session_ids = [str(uuid.UUID(int=rng.getrandbits(128))) for _ in range(max_sessions)]
    totals = {model.__tablename__: 0 for model in _MODELS}
    ip_start = 1
    with engine.begin() as conn:
        for device in devices:
            mac_ids = _deal(slots, int(device.get("mac", {}).get("distinct_macs", 0)), fresh)
            wanted = int(device.get("arp", {}).get("distinct_macs", 0))
            from_pool = round(wanted * arp_in_pool)
            arp_ids = rng.sample(range(pool_size), min(from_pool, pool_size))
            arp_ids += [next(fresh) for _ in range(wanted - len(arp_ids))]
            rows = _device_rows(device, mac_ids, arp_ids, rng, ip_start)
            ip_start += int(device.get("arp", {}).get("distinct_ips", 0))
            kept = int(device.get("sessions", 1))
            for offset in range(max_sessions - kept, max_sessions):
                stamp = now - timedelta(days=max_sessions - offset)
                common = {"session_id": session_ids[offset], "collected_at": stamp}
                conn.execute(
                    insert(ClientDataCollection),
                    [
                        {
                            **common,
                            "device_name": device["id"],
                            "arp_status": device.get("arp_status", "skipped"),
                            "mac_status": device.get("mac_status", "skipped"),
                            "neighbor_status": device.get("neighbor_status", "skipped"),
                            "vrf_status": "ok" if device.get("arp") else "skipped",
                            "arp_rows": len(rows["arp"]),
                            "mac_rows": len(rows["mac"]),
                            "neighbor_rows": len(rows["nb"]),
                        }
                    ],
                )
                totals[ClientDataCollection.__tablename__] += 1
                for key, model in (
                    ("mac", ClientMacAddress),
                    ("arp", ClientIpAddress),
                    ("host", ClientHostname),
                    ("nb", ClientPortNeighbor),
                ):
                    stamped = [{**row, **common} for row in rows[key]]
                    for batch in _batches(stamped):
                        conn.execute(insert(model), list(batch))
                    totals[model.__tablename__] += len(stamped)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        for model in _MODELS:
            conn.exec_driver_sql(f"ANALYZE {model.__tablename__}")  # fixed names, no user input
    return totals
