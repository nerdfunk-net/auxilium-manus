"""Write path and retention for the client data tables.

A *collection* is everything one run wrote for one device (``session_id`` + ``device_name``,
recorded in ``client_data_collections``). Writing the same collection again replaces it, and
each device keeps only its newest ``keep_sessions`` collections. The read queries live in
``client_data_query_repository``.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import cast

from sqlalchemy import CursorResult, and_, delete, func, select, tuple_
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from core.models.client_data import (
    ClientDataCollection,
    ClientHostname,
    ClientIpAddress,
    ClientMacAddress,
    ClientPortNeighbor,
    table_was_read,
)
from models.client_data import (
    ClientCollectionStatus,
    ClientHostnameRow,
    ClientIpRow,
    ClientMacRow,
    ClientNeighborRow,
    CollectionConflictError,
)

# Tables that hold a collection's rows, in deletion order.
_ROW_MODELS = (
    ClientIpAddress,
    ClientMacAddress,
    ClientHostname,
    ClientPortNeighbor,
    ClientDataCollection,
)


# What each dialect names when ``uq_client_data_collection_session`` is violated: PostgreSQL
# the constraint, SQLite the table and first column.
_COLLECTION_KEY_MARKERS = (
    "uq_client_data_collection_session",
    "client_data_collections.session_id",
)


def _violates_collection_key(exc: IntegrityError) -> bool:
    detail = str(exc.orig)
    return any(marker in detail for marker in _COLLECTION_KEY_MARKERS)


class ClientDataRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def replace_device_collection(
        self,
        *,
        session_id: str,
        device_name: str,
        device_ip: str | None,
        collected_at: datetime,
        ip_rows: Sequence[ClientIpRow],
        mac_rows: Sequence[ClientMacRow],
        hostname_rows: Sequence[ClientHostnameRow],
        status: ClientCollectionStatus,
        keep_sessions: int,
        target_host: str | None = None,
        neighbor_rows: Sequence[ClientNeighborRow] = (),
    ) -> None:
        """Store one device's collection in a single transaction.

        A collection already stored for this ``session_id`` and ``device_name`` from a different
        ``target_host`` is another device with the same name: ``CollectionConflictError`` is raised
        and the stored rows stay. The same target (a retry or rerun) replaces its own rows; an
        unknown host on either side counts as the same.

        The device's earlier rows for this ``session_id`` are deleted first, so a retried
        step does not duplicate them; then the device's collections beyond the newest
        ``keep_sessions`` are pruned. Any database error rolls back and leaves the earlier
        collection untouched.
        """
        if keep_sessions < 1:
            raise ValueError("keep_sessions must be at least 1")
        target_host = target_host[:255] if target_host else None
        self._refuse_other_device(
            session_id=session_id, device_name=device_name, target_host=target_host
        )
        common = {
            "session_id": session_id,
            "device_name": device_name,
            "collected_at": collected_at,
        }
        try:
            self._delete_collection(session_id=session_id, device_name=device_name)
            self.db.add_all(
                [
                    *(
                        ClientIpAddress(**common, device_ip=device_ip, **row.model_dump())
                        for row in ip_rows
                    ),
                    *(
                        ClientMacAddress(**common, device_ip=device_ip, **row.model_dump())
                        for row in mac_rows
                    ),
                    *(
                        ClientHostname(**common, device_ip=device_ip, **row.model_dump())
                        for row in hostname_rows
                    ),
                    *(
                        ClientPortNeighbor(**common, device_ip=device_ip, **row.model_dump())
                        for row in neighbor_rows
                    ),
                    ClientDataCollection(
                        **common,
                        **status.model_dump(),
                        target_host=target_host,
                        arp_rows=len(ip_rows),
                        mac_rows=len(mac_rows),
                        neighbor_rows=len(neighbor_rows),
                    ),
                ]
            )
            self.db.flush()
            self._prune_device(
                device_name=device_name, keep_sessions=keep_sessions, current_session=session_id
            )
            self.db.commit()
        except IntegrityError as exc:
            self.db.rollback()
            if _violates_collection_key(exc):
                raise CollectionConflictError from exc
            raise
        except SQLAlchemyError:
            self.db.rollback()
            raise

    def _refuse_other_device(
        self, *, session_id: str, device_name: str, target_host: str | None
    ) -> None:
        """Raise when this run already holds a collection of that name from another target."""
        c = ClientDataCollection
        stored = self.db.scalars(
            select(c.target_host).where(c.session_id == session_id, c.device_name == device_name)
        ).all()
        if any(
            host is not None and target_host is not None and host != target_host for host in stored
        ):
            raise CollectionConflictError

    def purge_older_than(self, cutoff: datetime, *, batch_size: int = 1000) -> int:
        """Delete collections older than *cutoff*, except what is still current.

        Kept however old: each device's newest collection, and its newest collection of each
        table (ARP, MAC) that read it, so a device that is no longer collected, or whose later
        runs left a table out, still shows its last known state. Returns the rows deleted.
        """
        c = ClientDataCollection
        newest_first = (c.collected_at.desc(), c.id.desc())
        arp_read = table_was_read(c.arp_status)
        mac_read = table_was_read(c.mac_status)
        neighbor_read = table_was_read(c.neighbor_status)
        ranked = (
            select(
                c.id,
                c.session_id,
                c.device_name,
                c.collected_at,
                arp_read.label("arp_read"),
                mac_read.label("mac_read"),
                neighbor_read.label("neighbor_read"),
                func.row_number()
                .over(partition_by=c.device_name, order_by=newest_first)
                .label("rank_any"),
                func.row_number()
                .over(partition_by=(c.device_name, arp_read), order_by=newest_first)
                .label("rank_arp"),
                func.row_number()
                .over(partition_by=(c.device_name, mac_read), order_by=newest_first)
                .label("rank_mac"),
                func.row_number()
                .over(partition_by=(c.device_name, neighbor_read), order_by=newest_first)
                .label("rank_neighbor"),
            )
        ).subquery()
        stale = (
            select(ranked.c.session_id, ranked.c.device_name)
            .where(
                ranked.c.collected_at < cutoff,
                ranked.c.rank_any > 1,
                ~and_(ranked.c.arp_read, ranked.c.rank_arp == 1),
                ~and_(ranked.c.mac_read, ranked.c.rank_mac == 1),
                ~and_(ranked.c.neighbor_read, ranked.c.rank_neighbor == 1),
            )
            .order_by(ranked.c.id)
            .limit(batch_size)
        )
        deleted = 0
        try:
            while pairs := [tuple(row) for row in self.db.execute(stale)]:
                for model in _ROW_MODELS:
                    result = self.db.execute(
                        delete(model).where(tuple_(model.session_id, model.device_name).in_(pairs))
                    )
                    deleted += cast(CursorResult, result).rowcount or 0
                self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise
        return deleted

    def _delete_collection(self, *, session_id: str, device_name: str) -> None:
        for model in _ROW_MODELS:
            self.db.execute(
                delete(model).where(
                    model.session_id == session_id, model.device_name == device_name
                )
            )

    def _prune_device(self, *, device_name: str, keep_sessions: int, current_session: str) -> None:
        """Drop the device's collections beyond the newest *keep_sessions*, except what is current.

        Kept besides the newest ones: the collection being written (an overlapping run may have
        stored newer ones while this run was still on the wire, and a write that reports success
        must not delete its own rows) and the newest collection of each table that read it, so
        keep-N runs that left ARP or the MAC table out cannot prune away its last rows.
        """
        c = ClientDataCollection
        newest_first = (c.collected_at.desc(), c.id.desc())
        ranked = list(
            self.db.scalars(
                select(c.session_id).where(c.device_name == device_name).order_by(*newest_first)
            )
        )
        protected = {current_session}
        for read in (
            table_was_read(c.arp_status),
            table_was_read(c.mac_status),
            table_was_read(c.neighbor_status),
        ):
            newest = self.db.scalar(
                select(c.session_id)
                .where(c.device_name == device_name, read)
                .order_by(*newest_first)
                .limit(1)
            )
            if newest is not None:
                protected.add(newest)
        stale_sessions = [sid for sid in ranked[keep_sessions:] if sid not in protected]
        if not stale_sessions:
            return
        for model in _ROW_MODELS:
            self.db.execute(
                delete(model).where(
                    model.device_name == device_name, model.session_id.in_(stale_sessions)
                )
            )
