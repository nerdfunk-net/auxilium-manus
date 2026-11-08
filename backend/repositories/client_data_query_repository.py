"""Read queries over the client data tables.

"Current" data is, per device and per table, the newest collection in which that table was
collected (``client_data_collections``, status not ``skipped``): a run may cover only some devices
or only one table, and an empty or refusing newest collection must hide the older rows of that
table. ARP (with VRFs and hostnames) and the MAC table are therefore current independently.
Only window functions are used, so the queries run on PostgreSQL and on SQLite (unit tests).
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    Integer,
    Select,
    String,
    and_,
    case,
    cast,
    func,
    literal,
    null,
    nulls_last,
    or_,
    select,
    union_all,
)
from sqlalchemy.dialects.postgresql import INET
from sqlalchemy.orm import InstrumentedAttribute, Session

from core.models.client_data import (
    ClientDataCollection,
    ClientHostname,
    ClientIpAddress,
    ClientMacAddress,
    ClientPortNeighbor,
    table_was_read,
)

_LIKE_ESCAPE = "\\"
_MAC_SEPARATORS = re.compile(r"[.:\-\s]")
_MAC_DIGITS = re.compile(r"^[0-9a-f]{12}$")
MAX_PAGE_SIZE = 500
# A port that learned more distinct MACs than this is treated as an uplink (a trunk to another
# switch), not as the place a host is plugged in.
DEFAULT_UPLINK_THRESHOLD = 10
MAX_HISTORY_ROWS = 1000
DEFAULT_HISTORY_ROWS = 500


def _contains(column: Any, value: str) -> Any:
    """Case-insensitive substring match; ``%``, ``_`` and ``\\`` in *value* are literal."""
    escaped = value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2).replace("%", r"\%").replace("_", r"\_")
    return column.ilike(f"%{escaped}%", escape=_LIKE_ESCAPE)


def _starts_with(column: Any, value: str) -> Any:
    escaped = value.replace(_LIKE_ESCAPE, _LIKE_ESCAPE * 2).replace("%", r"\%").replace("_", r"\_")
    return column.like(f"{escaped}%", escape=_LIKE_ESCAPE)


def _matches(column: Any, value: str, *, exact: bool, lowercase: bool = True) -> Any:
    """A substring match, or (exact) equality of the whole value ignoring case."""
    if not exact:
        return _contains(column, value)
    return func.lower(column) == value.strip().lower() if lowercase else column == value.strip()


def _canonical_ip(value: str) -> str:
    """The stored notation of an address (``str(ip_address(...))``): IPv6 is compressed and
    lower case. Text that is no address is returned stripped."""
    try:
        return str(ipaddress.ip_address(value.strip()))
    except ValueError:
        return value.strip()


def _dotted_mac(value: str) -> str:
    """The stored notation (aabb.ccdd.eeff) for any full MAC notation; other input unchanged."""
    digits = _MAC_SEPARATORS.sub("", value).lower()
    if _MAC_DIGITS.match(digits):
        return f"{digits[0:4]}.{digits[4:8]}.{digits[8:12]}"
    return value.strip()


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _latest_collections(table: str | None = None) -> Any:
    """Subquery ``(session_id, device_name)``: each device's newest collection.

    With ``table`` ("arp", "mac" or "neighbor") only collections that read that table count, so a
    later run that left it out (status ``skipped``), or whose output was not a table
    (``no_template``), does not hide its rows. ``not_supported`` and an empty table are
    observations and do supersede.
    """
    c = ClientDataCollection
    stmt = select(
        c.session_id,
        c.device_name,
        func.row_number()
        .over(partition_by=c.device_name, order_by=(c.collected_at.desc(), c.id.desc()))
        .label("rn"),
    )
    if table is not None:
        stmt = stmt.where(table_was_read(getattr(c, f"{table}_status")))
    ranked = stmt.subquery(f"collection_ranked_{table or 'any'}")
    return (
        select(ranked.c.session_id, ranked.c.device_name)
        .where(ranked.c.rn == 1)
        .subquery(f"latest_{table or 'any'}")
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


def _combined(uplink_threshold: int) -> Any:
    """The current observations, one row each, with the DNS hostname of the IP.

    * A MAC-table entry (MAC, device, VLAN, port) gets the IPs the same device has in ARP for that
      MAC and VLAN. Without one it falls back to an IP seen by any device for that MAC in the
      same VLAN, or in no known VLAN (a routed interface); only a MAC without a VLAN takes any
      IP. An IP seen in another VLAN is never attributed to the MAC.
    * ``macs_on_port`` counts the distinct MACs the device learned on that port. A port is an
      ``is_uplink`` when it has an infrastructure neighbour (a bridge, router or access point seen
      through LLDP/CDP, also through its port-channel; ``uplink_reason`` "neighbor",
      ``uplink_to`` the neighbour) or when it learned more MACs than the threshold
      (``uplink_reason`` "mac_count").
      Per MAC, the MAC-table observation on a non-uplink port with the fewest MACs (ties: device
      name, port) is the ``likely_location``.
    * An ARP entry that no MAC-table entry of its device matches is an observation of its own
      (port = the ARP interface), so an L3 device without a MAC table still shows its ARP.

    Each fallback is a single row per key, so the joins never multiply rows.
    """
    latest_mac = _latest_collections("mac")
    latest_arp = _latest_collections("arp")
    latest_neighbor = _latest_collections("neighbor")
    mac = ClientMacAddress
    ip = ClientIpAddress
    mac_entries = _newest(
        "mac_entries",
        mac,
        [mac.mac_address, mac.device_name, mac.vlan, mac.port, mac.session_id, mac.collected_at],
        [mac.mac_address, mac.device_name, mac.vlan, mac.port],
        latest_mac,
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
        latest_arp,
        where=ip.mac_address.is_not(None),
    )
    with_mac = ip.mac_address.is_not(None)
    ip_in_vlan = _newest(
        "ip_in_vlan",
        ip,
        [ip.mac_address, ip.vlan, ip.ip_address, ip.collected_at],
        [ip.mac_address, ip.vlan],
        latest_arp,
        where=and_(with_mac, ip.vlan.is_not(None)),
    )
    ip_without_vlan = _newest(
        "ip_without_vlan",
        ip,
        [ip.mac_address, ip.ip_address, ip.collected_at],
        [ip.mac_address],
        latest_arp,
        where=and_(with_mac, ip.vlan.is_(None)),
    )
    ip_any = _newest(
        "ip_any",
        ip,
        [ip.mac_address, ip.ip_address, ip.collected_at],
        [ip.mac_address],
        latest_arp,
        where=with_mac,
    )
    port_macs = (
        select(
            mac.device_name,
            mac.port,
            func.count(func.distinct(mac.mac_address)).label("macs_on_port"),
        )
        .select_from(mac)
        .join(
            latest_mac,
            and_(
                mac.session_id == latest_mac.c.session_id,
                mac.device_name == latest_mac.c.device_name,
            ),
        )
        .where(mac.port.is_not(None))
        .group_by(mac.device_name, mac.port)
        .cte("port_macs")
    )
    nb = ClientPortNeighbor
    current_neighbors = (
        select(nb.device_name, nb.port, nb.is_infrastructure, nb.neighbor_name)
        .select_from(nb)
        .join(
            latest_neighbor,
            and_(
                nb.session_id == latest_neighbor.c.session_id,
                nb.device_name == latest_neighbor.c.device_name,
            ),
        )
    )
    # A neighbour on a member port also makes the port-channel an uplink: the MAC table shows the
    # bundle (Po1), LLDP and CDP the member (Gi1/0/48).
    via_channel = current_neighbors.with_only_columns(
        nb.device_name,
        nb.channel.label("port"),
        nb.is_infrastructure,
        nb.neighbor_name,
    ).where(nb.channel.is_not(None))
    neighbor_ports = union_all(current_neighbors, via_channel).subquery("neighbor_ports")
    port_infra = (
        select(
            neighbor_ports.c.device_name,
            neighbor_ports.c.port,
            func.max(case((neighbor_ports.c.is_infrastructure, 1), else_=0)).label("infra"),
            # The neighbour behind the port; the lowest name when there are several.
            func.min(
                case((neighbor_ports.c.is_infrastructure, neighbor_ports.c.neighbor_name))
            ).label("uplink_to"),
        )
        .group_by(neighbor_ports.c.device_name, neighbor_ports.c.port)
        .cte("port_infra")
    )
    hostnames = _newest(
        "hostname_for_ip",
        ClientHostname,
        [ClientHostname.ip_address, ClientHostname.hostname],
        [ClientHostname.ip_address],
        latest_arp,
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
            port_macs.c.macs_on_port,
            port_infra.c.infra.label("neighbor_infra"),
            port_infra.c.uplink_to,
            # The IP can come from another ARP collection than the port: it has its own age.
            case(
                (arp_entries.c.ip_address.is_not(None), arp_entries.c.collected_at),
                (ip_in_vlan.c.ip_address.is_not(None), ip_in_vlan.c.collected_at),
                (ip_without_vlan.c.ip_address.is_not(None), ip_without_vlan.c.collected_at),
                (ip_any.c.ip_address.is_not(None), ip_any.c.collected_at),
                else_=None,
            ).label("ip_collected_at"),
        )
        .select_from(mac_entries)
        .outerjoin(
            port_macs,
            and_(
                port_macs.c.device_name == mac_entries.c.device_name,
                port_macs.c.port == mac_entries.c.port,
            ),
        )
        .outerjoin(
            port_infra,
            and_(
                port_infra.c.device_name == mac_entries.c.device_name,
                port_infra.c.port == mac_entries.c.port,
            ),
        )
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
            cast(null(), Integer).label("macs_on_port"),
            cast(null(), Integer).label("neighbor_infra"),
            cast(null(), String).label("uplink_to"),
            arp_entries.c.collected_at.label("ip_collected_at"),
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
    no_port_stats = observations.c.macs_on_port.is_(None)
    behind_neighbor = func.coalesce(observations.c.neighbor_infra, 0) == 1
    is_uplink_port = or_(observations.c.macs_on_port > literal(uplink_threshold), behind_neighbor)
    ranked = (
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
            observations.c.macs_on_port,
            observations.c.neighbor_infra,
            observations.c.uplink_to,
            observations.c.ip_collected_at,
            func.row_number()
            .over(
                # Rows without port statistics (ARP-only) rank among themselves, never first.
                partition_by=(observations.c.mac_address, no_port_stats),
                # Fully ordered, so equal scores pick the same row every time.
                order_by=(
                    # An uplink never beats an access port, however few MACs it has learned.
                    case((is_uplink_port, 1), else_=0),
                    observations.c.macs_on_port,
                    observations.c.device_name,
                    observations.c.port,
                    observations.c.vlan,
                    observations.c.vrf,
                    observations.c.ip_address,
                ),
            )
            .label("port_rank"),
        )
        .select_from(observations)
        .outerjoin(hostnames, observations.c.ip_address == hostnames.c.ip_address)
        .cte("ranked")
    )
    behind_neighbor = func.coalesce(ranked.c.neighbor_infra, 0) == 1
    over_count = ranked.c.macs_on_port > literal(uplink_threshold)
    uplink = or_(over_count, behind_neighbor)
    return (
        select(
            ranked.c.mac_address,
            ranked.c.device_name,
            ranked.c.port,
            ranked.c.vlan,
            ranked.c.vrf,
            ranked.c.ip_address,
            ranked.c.hostname,
            ranked.c.session_id,
            ranked.c.collected_at,
            ranked.c.macs_on_port,
            ranked.c.ip_collected_at,
            case((uplink, True), else_=False).cast(Boolean).label("is_uplink"),
            # Why: a switch, router or access point seen through LLDP/CDP is more certain than
            # the number of MACs.
            case((behind_neighbor, "neighbor"), (over_count, "mac_count"), else_=None).label(
                "uplink_reason"
            ),
            case((behind_neighbor, ranked.c.uplink_to), else_=None).label("uplink_to"),
            case(
                (and_(ranked.c.macs_on_port.is_not(None), ranked.c.port_rank == 1, ~uplink), True),
                else_=False,
            )
            .cast(Boolean)
            .label("likely_location"),
        )
        .select_from(ranked)
        .cte("combined")
    )


class ClientDataQueryRepository:
    def __init__(self, db: Session, *, uplink_threshold: int = DEFAULT_UPLINK_THRESHOLD) -> None:
        if uplink_threshold < 1:
            raise ValueError("uplink_threshold must be at least 1")
        self.db = db
        self.uplink_threshold = uplink_threshold

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
        hide_uplinks: bool = False,
        exact: bool = False,
        likely_first: bool = False,
        ip_prefix: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """Correlated client data (one row per MAC and device), filtered and paginated.

        Every filter is a case-insensitive substring match, or with ``exact`` a whole-value match
        (the MAC and the IPv6 address in any notation). ``ip_prefix`` matches the start of the
        address. ``hide_uplinks`` leaves out MAC-table rows on uplink ports. ``likely_first``
        orders the likely location, then access ports, then uplinks before paging, so the best
        answer is on the first page whatever the size of the result. Returns ``(rows, total)``.
        """
        if page < 1:
            raise ValueError("page must be at least 1")
        if not 1 <= page_size <= MAX_PAGE_SIZE:
            raise ValueError(f"page_size must be between 1 and {MAX_PAGE_SIZE}")
        combined = _combined(self.uplink_threshold)
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
            _matches(combined.c[key], value, exact=exact)
            for key, value in filters.items()
            if value and key not in ("mac_address", "ip_address")
        ]
        if ip_address:
            if exact:
                conditions.append(combined.c.ip_address == _canonical_ip(ip_address))
            else:
                conditions.append(_contains(combined.c.ip_address, ip_address))
        if ip_prefix and ip_prefix.strip():
            conditions.append(_starts_with(combined.c.ip_address, ip_prefix.strip()))
        if mac_address:
            # Stored as aabb.ccdd.eeff: compare without separators, so aa:bb:cc... also matches.
            if exact:
                conditions.append(combined.c.mac_address == _dotted_mac(mac_address))
            else:
                typed = _MAC_SEPARATORS.sub("", mac_address).lower()
                conditions.append(_contains(func.replace(combined.c.mac_address, ".", ""), typed))
        if hide_uplinks:
            conditions.append(combined.c.is_uplink.is_(False))

        count_stmt = select(func.count()).select_from(combined)
        order = [
            nulls_last(self._ip_sort_key(combined.c.ip_address).asc()),
            combined.c.mac_address,
            combined.c.device_name,
        ]
        if likely_first:
            order = [combined.c.likely_location.desc(), combined.c.is_uplink.asc(), *order]
        data_stmt = select(combined).order_by(*order)
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
                "macs_on_port": row.macs_on_port,
                "ip_collected_at": _iso(row.ip_collected_at) if row.ip_address else None,
                "is_uplink": bool(row.is_uplink),
                "uplink_reason": row.uplink_reason,
                "uplink_to": row.uplink_to,
                "likely_location": bool(row.likely_location),
                "session_id": row.session_id,
                "collected_at": _iso(row.collected_at),
            }
            for row in self.db.execute(data_stmt)
        ]
        return items, total

    def get_collections(self) -> list[dict[str, Any]]:
        """Coverage: per device, each table's newest collection, sorted by device.

        ``collected_at`` is the newest of the two; ``arp_*`` and ``mac_*`` say when and how each
        table was last read (``skipped`` and ``None`` when it never was). VRF discovery belongs to
        the ARP collection.
        """
        by_table = {table: self._latest_rows(table) for table in ("arp", "mac", "neighbor")}
        coverage: list[dict[str, Any]] = []
        for device in sorted(
            set(by_table["arp"]) | set(by_table["mac"]) | set(by_table["neighbor"])
        ):
            arp = by_table["arp"].get(device)
            mac = by_table["mac"].get(device)
            neighbor = by_table["neighbor"].get(device)
            stamps = [row.collected_at for row in (arp, mac, neighbor) if row is not None]
            coverage.append(
                {
                    "device_name": device,
                    "collected_at": _iso(max(stamps)),
                    "arp_collected_at": _iso(arp.collected_at) if arp else None,
                    "mac_collected_at": _iso(mac.collected_at) if mac else None,
                    "arp_status": arp.arp_status if arp else "skipped",
                    "mac_status": mac.mac_status if mac else "skipped",
                    "vrf_status": arp.vrf_status if arp else "skipped",
                    "vrf_count": arp.vrf_count if arp else 0,
                    "vrfs": arp.vrfs if arp else None,
                    "arp_rows": arp.arp_rows if arp else 0,
                    "mac_rows": mac.mac_rows if mac else 0,
                    "neighbor_collected_at": _iso(neighbor.collected_at) if neighbor else None,
                    "neighbor_status": neighbor.neighbor_status if neighbor else "skipped",
                    "neighbor_rows": neighbor.neighbor_rows if neighbor else 0,
                }
            )
        return coverage

    def _ip_sort_key(self, column: Any) -> Any:
        """Numeric order (``10.0.0.2`` before ``10.0.0.10``, IPv4 before IPv6) on PostgreSQL.

        Stored addresses are validated, so the ``inet`` cast cannot fail. SQLite (unit tests) has
        no ``inet`` and keeps the string order.
        """
        if self.db.get_bind().dialect.name == "postgresql":
            return cast(column, INET)
        return column

    def _latest_rows(self, table: str) -> dict[str, ClientDataCollection]:
        latest = _latest_collections(table)
        c = ClientDataCollection
        stmt = select(c).join(
            latest,
            and_(c.session_id == latest.c.session_id, c.device_name == latest.c.device_name),
        )
        return {row.device_name: row for row in self.db.scalars(stmt)}

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

    def _collapsed(
        self,
        stmt: Select,
        *,
        partition: Sequence[Any],
        order: Sequence[Any],
        newest: Sequence[Any],
        limit: int,
    ) -> list[Any]:
        """One row per *partition* (the best by *order*), newest first, at most *limit*.

        The collapse happens in SQL before the limit: a join that repeats a stored row must not use
        up the limit, or older collections would drop out of a history that is called complete.
        """
        ranked = stmt.add_columns(
            func.row_number().over(partition_by=partition, order_by=order).label("rn")
        ).subquery()
        return list(
            self.db.execute(
                select(ranked)
                .where(ranked.c.rn == 1)
                .order_by(*(ranked.c[name].desc() for name in newest))
                .limit(limit)
            )
        )

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
                i.id.label("row_id"),
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
            .where(i.ip_address == _canonical_ip(ip_address))
        )
        rows = self._collapsed(
            stmt,
            partition=(i.session_id, i.device_name, i.mac_address, i.vrf),
            order=(m.vlan, m.port),
            newest=("collected_at", "row_id"),
            limit=limit,
        )
        return [
            {
                "ip_address": r.ip_address,
                "mac_address": r.mac_address,
                "port": r.port,
                "vlan": r.vlan,
                "vrf": r.vrf,
                "device_name": r.device_name,
                "collected_at": _iso(r.collected_at),
            }
            for r in rows
        ]

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
                m.id.label("row_id"),
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
        )
        rows = self._collapsed(
            stmt,
            partition=(m.session_id, m.device_name, m.vlan, m.port, i.ip_address),
            order=(m.id,),
            newest=("collected_at", "row_id"),
            limit=limit,
        )
        return [
            {
                "mac_address": r.mac_address,
                "port": r.port,
                "vlan": r.vlan,
                "device_name": r.device_name,
                "ip_address": r.ip_address,
                "collected_at": _iso(r.collected_at),
            }
            for r in rows
        ]

    def _hostname_history(self, hostname: str, limit: int) -> list[dict[str, Any]]:
        h = ClientHostname
        stmt = select(
            h.session_id,
            h.hostname,
            h.ip_address,
            h.device_name,
            h.collected_at,
            h.id.label("row_id"),
        ).where(func.lower(h.hostname) == hostname.strip().lower())
        rows = self._collapsed(
            stmt,
            partition=(h.session_id, h.ip_address, h.hostname),
            order=(h.id,),
            newest=("collected_at", "row_id"),
            limit=limit,
        )
        return [
            {
                "hostname": r.hostname,
                "ip_address": r.ip_address,
                "device_name": r.device_name,
                "collected_at": _iso(r.collected_at),
            }
            for r in rows
        ]
