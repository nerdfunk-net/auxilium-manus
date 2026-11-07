"""Read queries over the client data tables.

"Current" data is each device's newest collection (``client_data_collections``), not one
global latest run: a run may cover only some devices, and an empty newest collection must
hide that device's older rows. Only window functions are used, so the queries run on
PostgreSQL and on SQLite (unit tests).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, func, nulls_last, select, union_all
from sqlalchemy.orm import InstrumentedAttribute, Session

from core.models.client_data import (
    ClientDataCollection,
    ClientHostname,
    ClientIpAddress,
    ClientMacAddress,
)

_LIKE_ESCAPE = "\\"
_MAC_SEPARATORS = re.compile(r"[.:\-\s]")
_MAC_DIGITS = re.compile(r"^[0-9a-f]{12}$")
MAX_PAGE_SIZE = 500
MAX_HISTORY_ROWS = 1000
DEFAULT_HISTORY_ROWS = 500


def _contains(column: Any, value: str) -> Any:
    """Case-insensitive substring match; ``%``, ``_`` and ``\\`` in *value* are literal."""
    escaped = value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2).replace("%", r"\%").replace("_", r"\_")
    return column.ilike(f"%{escaped}%", escape=_LIKE_ESCAPE)


def _dotted_mac(value: str) -> str:
    """The stored notation (aabb.ccdd.eeff) for any full MAC notation; other input unchanged."""
    digits = _MAC_SEPARATORS.sub("", value).lower()
    if _MAC_DIGITS.match(digits):
        return f"{digits[0:4]}.{digits[4:8]}.{digits[8:12]}"
    return value.strip()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _latest_collections() -> Any:
    """Subquery ``(session_id, device_name)``: each device's newest collection."""
    ranked = select(
        ClientDataCollection.session_id,
        ClientDataCollection.device_name,
        func.row_number()
        .over(
            partition_by=ClientDataCollection.device_name,
            order_by=(ClientDataCollection.collected_at.desc(), ClientDataCollection.id.desc()),
        )
        .label("rn"),
    ).subquery("collection_ranked")
    return (
        select(ranked.c.session_id, ranked.c.device_name).where(ranked.c.rn == 1).subquery("latest")
    )


def _newest(
    name: str,
    model: Any,
    columns: Sequence[InstrumentedAttribute[Any]],
    partition: Sequence[InstrumentedAttribute[Any]],
    latest: Any,
    where: Any = None,
) -> Any:
    """CTE of *columns*: the newest row per *partition* among the current collections."""
    ranked_stmt: Select[Any] = (
        select(
            *columns,
            func.row_number()
            .over(partition_by=partition, order_by=(model.collected_at.desc(), model.id.desc()))
            .label("rn"),
        )
        .select_from(model)
        .join(
            latest,
            and_(
                model.session_id == latest.c.session_id,
                model.device_name == latest.c.device_name,
            ),
        )
    )
    if where is not None:
        ranked_stmt = ranked_stmt.where(where)
    ranked = ranked_stmt.subquery(f"{name}_ranked")
    return select(*(ranked.c[column.key] for column in columns)).where(ranked.c.rn == 1).cte(name)


def _combined() -> Any:
    """The current observations, one row each, with the DNS hostname of the IP.

    * A MAC-table entry (MAC, device, VLAN, port) gets the IPs the same device has in ARP for that
      MAC and VLAN. Without one it falls back to an IP seen by any device for that MAC in the
      same VLAN, or in no known VLAN (a routed interface); only a MAC without a VLAN takes any
      IP. An IP seen in another VLAN is never attributed to the MAC.
    * An ARP entry that no MAC-table entry of its device matches is an observation of its own
      (port = the ARP interface), so an L3 device without a MAC table still shows its ARP.

    Each fallback is a single row per key, so the joins never multiply rows.
    """
    latest = _latest_collections()
    mac = ClientMacAddress
    ip = ClientIpAddress
    mac_entries = _newest(
        "mac_entries",
        mac,
        [mac.mac_address, mac.device_name, mac.vlan, mac.port, mac.session_id, mac.collected_at],
        [mac.mac_address, mac.device_name, mac.vlan, mac.port],
        latest,
    )
    arp_entries = _newest(
        "arp_entries",
        ip,
        [
            ip.mac_address,
            ip.device_name,
            ip.ip_address,
            ip.interface,
            ip.vrf,
            ip.vlan,
            ip.session_id,
            ip.collected_at,
        ],
        [ip.mac_address, ip.device_name, ip.ip_address, ip.vrf],
        latest,
        where=ip.mac_address.is_not(None),
    )
    with_mac = ip.mac_address.is_not(None)
    ip_in_vlan = _newest(
        "ip_in_vlan",
        ip,
        [ip.mac_address, ip.vlan, ip.ip_address],
        [ip.mac_address, ip.vlan],
        latest,
        where=and_(with_mac, ip.vlan.is_not(None)),
    )
    ip_without_vlan = _newest(
        "ip_without_vlan",
        ip,
        [ip.mac_address, ip.ip_address],
        [ip.mac_address],
        latest,
        where=and_(with_mac, ip.vlan.is_(None)),
    )
    ip_any = _newest(
        "ip_any", ip, [ip.mac_address, ip.ip_address], [ip.mac_address], latest, where=with_mac
    )
    hostnames = _newest(
        "hostname_for_ip",
        ClientHostname,
        [ClientHostname.ip_address, ClientHostname.hostname],
        [ClientHostname.ip_address],
        latest,
    )

    from_mac_table = (
        select(
            mac_entries.c.mac_address,
            mac_entries.c.device_name,
            mac_entries.c.port.label("port"),
            mac_entries.c.vlan,
            arp_entries.c.vrf,
            func.coalesce(
                arp_entries.c.ip_address,
                ip_in_vlan.c.ip_address,
                ip_without_vlan.c.ip_address,
                ip_any.c.ip_address,
            ).label("ip_address"),
            mac_entries.c.session_id,
            mac_entries.c.collected_at,
        )
        .select_from(mac_entries)
        .outerjoin(
            arp_entries,
            and_(
                arp_entries.c.mac_address == mac_entries.c.mac_address,
                arp_entries.c.device_name == mac_entries.c.device_name,
                arp_entries.c.vlan.is_not_distinct_from(mac_entries.c.vlan),
            ),
        )
        .outerjoin(
            ip_in_vlan,
            and_(
                ip_in_vlan.c.mac_address == mac_entries.c.mac_address,
                ip_in_vlan.c.vlan == mac_entries.c.vlan,
            ),
        )
        .outerjoin(ip_without_vlan, ip_without_vlan.c.mac_address == mac_entries.c.mac_address)
        .outerjoin(
            ip_any,
            and_(
                ip_any.c.mac_address == mac_entries.c.mac_address,
                mac_entries.c.vlan.is_(None),
            ),
        )
    )
    unmatched_arp = (
        select(
            arp_entries.c.mac_address,
            arp_entries.c.device_name,
            arp_entries.c.interface.label("port"),
            arp_entries.c.vlan,
            arp_entries.c.vrf,
            arp_entries.c.ip_address,
            arp_entries.c.session_id,
            arp_entries.c.collected_at,
        )
        .select_from(arp_entries)
        .outerjoin(
            mac_entries,
            and_(
                mac_entries.c.mac_address == arp_entries.c.mac_address,
                mac_entries.c.device_name == arp_entries.c.device_name,
                mac_entries.c.vlan.is_not_distinct_from(arp_entries.c.vlan),
            ),
        )
        .where(mac_entries.c.mac_address.is_(None))
    )
    observations = union_all(from_mac_table, unmatched_arp).cte("observations")
    return (
        select(
            observations.c.mac_address,
            observations.c.device_name,
            observations.c.port,
            observations.c.vlan,
            observations.c.vrf,
            observations.c.ip_address,
            hostnames.c.hostname,
            observations.c.session_id,
            observations.c.collected_at,
        )
        .select_from(observations)
        .outerjoin(hostnames, observations.c.ip_address == hostnames.c.ip_address)
        .cte("combined")
    )


class ClientDataQueryRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def get_client_data(
        self,
        *,
        device_name: str | None = None,
        ip_address: str | None = None,
        mac_address: str | None = None,
        port: str | None = None,
        vlan: str | None = None,
        vrf: str | None = None,
        hostname: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """Correlated client data (one row per MAC and device), filtered and paginated.

        Every filter is a case-insensitive substring match. Returns ``(rows, total)``.
        """
        if page < 1:
            raise ValueError("page must be at least 1")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        combined = _combined()
        filters = {
            "device_name": device_name,
            "ip_address": ip_address,
            "mac_address": mac_address,
            "port": port,
            "vlan": vlan,
            "vrf": vrf,
            "hostname": hostname,
        }
        conditions = [
            _contains(combined.c[key], value)
            for key, value in filters.items()
            if value and key != "mac_address"
        ]
        if mac_address:
            # Stored as aabb.ccdd.eeff: compare without separators, so aa:bb:cc... also matches.
            typed = _MAC_SEPARATORS.sub("", mac_address).lower()
            conditions.append(_contains(func.replace(combined.c.mac_address, ".", ""), typed))

        count_stmt = select(func.count()).select_from(combined)
        data_stmt = select(combined).order_by(
            nulls_last(combined.c.ip_address.asc()),
            combined.c.mac_address,
            combined.c.device_name,
        )
        if conditions:
            count_stmt = count_stmt.where(*conditions)
            data_stmt = data_stmt.where(*conditions)
        data_stmt = data_stmt.limit(page_size).offset((page - 1) * page_size)

        total = self.db.execute(count_stmt).scalar() or 0
        items = [
            {
                "mac_address": row.mac_address,
                "port": row.port,
                "vlan": row.vlan,
                "vrf": row.vrf,
                "ip_address": row.ip_address,
                "hostname": row.hostname,
                "device_name": row.device_name,
                "session_id": row.session_id,
                "collected_at": _iso(row.collected_at),
            }
            for row in self.db.execute(data_stmt)
        ]
        return items, total

    def get_device_names(self) -> list[str]:
        """Devices that have a current collection, sorted."""
        latest = _latest_collections()
        return list(self.db.scalars(select(latest.c.device_name).order_by(latest.c.device_name)))

    def get_client_history(
        self,
        *,
        ip_address: str | None = None,
        mac_address: str | None = None,
        hostname: str | None = None,
        limit: int = DEFAULT_HISTORY_ROWS,
    ) -> dict[str, list[dict[str, Any]]]:
        """Observations of an IP, MAC or hostname across all retained collections, newest first.

        The MAC may be given in any notation and the hostname in any case; each list holds at
        most *limit* rows.
        """
        if not 1 <= limit <= MAX_HISTORY_ROWS:
            raise ValueError(f"limit must be between 1 and {MAX_HISTORY_ROWS}")
        return {
            "ip_history": self._ip_history(ip_address, limit) if ip_address else [],
            "mac_history": self._mac_history(_dotted_mac(mac_address), limit)
            if mac_address
            else [],
            "hostname_history": self._hostname_history(hostname, limit) if hostname else [],
        }

    def _ip_history(self, ip_address: str, limit: int) -> list[dict[str, Any]]:
        i, m = ClientIpAddress, ClientMacAddress
        stmt = (
            select(
                i.session_id,
                i.ip_address,
                i.mac_address,
                func.coalesce(m.port, i.interface).label("port"),
                func.coalesce(m.vlan, i.vlan).label("vlan"),
                i.vrf,
                i.device_name,
                i.collected_at,
            )
            .select_from(i)
            .outerjoin(
                m,
                and_(
                    m.mac_address == i.mac_address,
                    m.device_name == i.device_name,
                    m.session_id == i.session_id,
                ),
            )
            .where(i.ip_address == ip_address)
            .order_by(i.collected_at.desc(), i.id.desc())
            .limit(limit)
        )
        return _first_per_collection(
            self.db.execute(stmt),
            ("ip_address", "mac_address", "port", "vlan", "vrf", "device_name"),
            key=("session_id", "device_name", "mac_address", "vrf"),
        )

    def _mac_history(self, mac_address: str, limit: int) -> list[dict[str, Any]]:
        m, i = ClientMacAddress, ClientIpAddress
        stmt = (
            select(
                m.session_id,
                m.mac_address,
                m.port,
                m.vlan,
                m.device_name,
                m.collected_at,
                i.ip_address,
            )
            .select_from(m)
            .outerjoin(
                i,
                and_(
                    i.mac_address == m.mac_address,
                    i.device_name == m.device_name,
                    i.session_id == m.session_id,
                ),
            )
            .where(m.mac_address == mac_address)
            .order_by(m.collected_at.desc(), m.id.desc())
            .limit(limit)
        )
        return _first_per_collection(
            self.db.execute(stmt),
            ("mac_address", "port", "vlan", "device_name", "ip_address"),
            key=("session_id", "device_name", "vlan", "port", "ip_address"),
        )

    def _hostname_history(self, hostname: str, limit: int) -> list[dict[str, Any]]:
        h = ClientHostname
        stmt = (
            select(h.session_id, h.hostname, h.ip_address, h.device_name, h.collected_at)
            .where(func.lower(h.hostname) == hostname.strip().lower())
            .order_by(h.collected_at.desc(), h.id.desc())
            .limit(limit)
        )
        return _first_per_collection(
            self.db.execute(stmt),
            ("hostname", "ip_address", "device_name"),
            key=("session_id", "ip_address", "hostname"),
        )


def _first_per_collection(
    rows: Any, fields: tuple[str, ...], *, key: tuple[str, ...]
) -> list[dict[str, Any]]:
    """Keep the first (newest) row per *key*; rows arrive ordered newest first."""
    seen: set[tuple[Any, ...]] = set()
    history: list[dict[str, Any]] = []
    for row in rows:
        marker = tuple(getattr(row, name) for name in key)
        if marker in seen:
            continue
        seen.add(marker)
        entry = {field: getattr(row, field) for field in fields}
        entry["collected_at"] = _iso(row.collected_at)
        history.append(entry)
    return history
