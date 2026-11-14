"""Nautobot as a report source: virtual datasets read live, queried in memory.

This is not a second Nautobot connection. The configured Nautobot source (Settings -> Sources)
stays the only place with a URL and a token; this adapter asks the shared read library
(``libs/nautobot_read``, the same one Ask the Net uses) for the rows, as the calling user, and
applies the Reports query (``row_evaluator``) to them. That way a saved report, a template, a
snapshot, the PDF and the e-mail work the same for Nautobot data as for stored report data.

The catalog is static (no Nautobot call to list it). ``run`` fetches the rows on demand, so
every generated snapshot is a fresh copy of Nautobot; the snapshot keeps it afterwards.
``run`` is synchronous like every ``ReportSource`` and is called from a worker thread, where
``asyncio.run`` is safe (a request thread of FastAPI or ``asyncio.to_thread``); it must not be
called from a thread that runs an event loop.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from nautobot_read.client import NautobotError, TooManyRowsError
from nautobot_read.context import QueryContext
from nautobot_read.queries.dcim import DEVICE_SELECTION, INTERFACE_SELECTION, device_item
from nautobot_read.queries.locations import directory_or_none
from sqlalchemy.orm import Session

from models.reports import DatasetInfo, FieldInfo, FieldType, QueryResult, ReportQuery
from services.reports.errors import ReportQueryError
from services.reports.sources.row_evaluator import Row, evaluate, validate

logger = logging.getLogger(__name__)

SOURCE_ID = "nautobot"
# A report reads at most this many rows of one table; more is an error, never a silently cut
# list.
MAX_DEVICES = 5000

ContextFactory = Callable[[int], Awaitable[QueryContext]]

_DEVICE_FIELDS: tuple[tuple[str, FieldType], ...] = (
    ("role", "string"),
    ("status", "string"),
    ("device_type", "string"),
    ("manufacturer", "string"),
    ("platform", "string"),
    ("location", "string"),
    ("primary_ip4", "string"),
    ("serial", "string"),
    ("tags", "string"),
    ("software_version", "string"),
    ("software_lts", "boolean"),
    ("software_images", "string"),
)
# The shared device selection plus the software of the device (Nautobot 2.2 and later). It is
# kept here, not in the shared library, so Ask the Net's own device reads do not depend on it.
SOFTWARE_SELECTION = (
    "software_version { version long_term_support software_image_files { image_file_name } }"
)
REPORT_DEVICE_SELECTION = f"{DEVICE_SELECTION} {SOFTWARE_SELECTION}"
_SOFTWARE_VERSION_FIELDS: tuple[tuple[str, FieldType], ...] = (
    ("version", "string"),
    ("platform", "string"),
    ("manufacturer", "string"),
    ("long_term_support", "boolean"),
    ("device_count", "number"),
    ("image_files", "string"),
)
# Software versions seen from the software side: also those no device runs (device_count 0).
SOFTWARE_VERSION_SELECTION = (
    "id version long_term_support platform { name manufacturer { name } } "
    "software_image_files { image_file_name } devices { id }"
)
_INTERFACE_FIELDS: tuple[tuple[str, FieldType], ...] = (
    ("interface", "string"),
    ("type", "string"),
    ("enabled", "boolean"),
    ("status", "string"),
    ("mac_address", "string"),
    ("description", "string"),
    ("ip_addresses", "string"),
    ("cabled", "boolean"),
    ("connected_device", "string"),
    ("connected_interface", "string"),
)
# Interfaces are read from the top level (one list, not nested per device) and name their device.
REPORT_INTERFACE_SELECTION = f"device {{ name }} {INTERFACE_SELECTION}"
_IP_ADDRESS_FIELDS: tuple[tuple[str, FieldType], ...] = (
    ("address", "string"),
    ("prefix", "string"),
    ("namespace", "string"),
    ("status", "string"),
    ("role", "string"),
    ("type", "string"),
    ("dns_name", "string"),
    ("description", "string"),
    ("tenant", "string"),
    ("tags", "string"),
    ("assigned_to", "string"),
)
IP_ADDRESS_SELECTION = (
    "address dns_name type description status { name } role { name } "
    "parent { prefix namespace { name } } tenant { name } tags { name } "
    "interfaces { name device { name } }"
)
_PREFIX_FIELDS: tuple[tuple[str, FieldType], ...] = (
    ("prefix", "string"),
    ("type", "string"),
    ("namespace", "string"),
    ("status", "string"),
    ("role", "string"),
    ("description", "string"),
    ("tenant", "string"),
    ("vlan", "string"),
    ("locations", "string"),
    ("parent", "string"),
    ("tags", "string"),
    ("size", "number"),
    ("used_ip_count", "number"),
    ("free_ip_count", "number"),
)
PREFIX_REPORT_SELECTION = (
    "prefix type status { name } role { name } namespace { name } description "
    "tenant { name } vlan { vid name } locations { name } tags { name } parent { prefix } "
    "ip_addresses { id }"
)
_LOCATION_FIELDS: tuple[tuple[str, FieldType], ...] = (
    ("location_type", "string"),
    ("parent", "string"),
)
LOCATION_SELECTION = "name location_type { name } parent { name }"


def _dataset(name: str, mode: Any, fields: tuple[tuple[str, FieldType], ...]) -> DatasetInfo:
    return DatasetInfo(
        name=name,
        mode=mode,
        fields=[
            FieldInfo(name=field, type=kind, null_share=0.0, sample_values=[])
            for field, kind in fields
        ],
    )


async def _default_context(user_id: int) -> QueryContext:
    # Imported late: the reader pulls in the service factory and the settings stack.
    from services.ai_assistant.nautobot_query_reader import DbNautobotQueryReader

    # Isolated: ``run`` works in an event loop of its own, so it must not touch the connection
    # pools and caches that belong to the main one (see ``DbNautobotQueryReader.context``).
    return await DbNautobotQueryReader(user_id).context(isolated=True)


def _texts(entries: Any, key: str) -> str:
    """The text ``key`` of each dict in the list ``entries`` joined by commas.

    Nautobot data is not trusted to have the shape the query asks for: a value that is not a list,
    an entry that is not a dict or a name that is null is left out. One odd nested value must not
    fail the whole section (and every device in it).
    """
    if not isinstance(entries, list):
        return ""
    found = [e.get(key) for e in entries if isinstance(e, dict)]
    return ", ".join(value for value in found if isinstance(value, str) and value)


def _software(raw: dict[str, Any]) -> dict[str, Any]:
    """The software fields of one raw device row; a device without software has none."""
    software = raw.get("software_version")
    software = software if isinstance(software, dict) else {}
    lts = software.get("long_term_support")
    return {
        "software_version": software.get("version"),
        "software_lts": lts if isinstance(lts, bool) else None,
        "software_images": _texts(software.get("software_image_files"), "image_file_name"),
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_device(raw: dict[str, Any]) -> dict[str, Any]:
    """A copy of the raw device whose nested objects are dicts (and whose name is text), so the
    shared ``device_item`` cannot fail on an odd value. Tags are read separately (``_texts``)."""
    device_type = _dict(raw.get("device_type"))
    return {
        **raw,
        "id": str(raw.get("id") or ""),
        "name": raw["name"] if isinstance(raw.get("name"), str) else "",
        "serial": raw["serial"] if isinstance(raw.get("serial"), str) else "",
        "role": _dict(raw.get("role")),
        "status": _dict(raw.get("status")),
        "platform": _dict(raw.get("platform")),
        "location": _dict(raw.get("location")),
        "primary_ip4": _dict(raw.get("primary_ip4")),
        "device_type": {**device_type, "manufacturer": _dict(device_type.get("manufacturer"))},
        "tags": [],
    }


def _device_row(raw: dict[str, Any], directory: Any) -> Row:
    """One raw device as a report row: empty text is a missing value, lists are one text."""
    item = {
        **device_item(_safe_device(raw), directory),
        **_software(raw),
        "tags": _texts(raw.get("tags"), "name"),
    }
    row: Row = {"device_name": item["name"]}
    for name, _ in _DEVICE_FIELDS:
        value = item.get(name)
        row[name] = value if value not in ("", [], None) else None
    return row


def _software_version_row(raw: dict[str, Any], _directory: Any) -> Row:
    """One software version as a report row. Its name is ``<platform> <version>`` (a version
    number alone repeats across platforms)."""
    platform = _dict(raw.get("platform"))
    manufacturer = _dict(platform.get("manufacturer"))
    version = raw["version"] if isinstance(raw.get("version"), str) else ""
    platform_name = platform["name"] if isinstance(platform.get("name"), str) else None
    lts = raw.get("long_term_support")
    devices = raw.get("devices")
    return {
        "device_name": f"{platform_name} {version}".strip() if platform_name else version,
        "version": version or None,
        "platform": platform_name,
        "manufacturer": manufacturer.get("name"),
        "long_term_support": lts if isinstance(lts, bool) else None,
        # Only a list can be counted. Any other shape is "unknown", never a number that looks
        # right (``len`` of a dict is its number of keys).
        "device_count": len(devices) if isinstance(devices, list) else None,
        "image_files": _texts(raw.get("software_image_files"), "image_file_name") or None,
    }


def _name_of(value: Any) -> str | None:
    name = _dict(value).get("name")
    return name if isinstance(name, str) and name else None


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _interface_row(raw: dict[str, Any], _directory: Any) -> Row:
    """One interface as a report row; ``device_name`` is its device."""
    cable = raw.get("cable")
    endpoint = _dict(raw.get("connected_endpoint"))
    peer = endpoint if endpoint.get("__typename") == "InterfaceType" else {}
    addresses = raw.get("ip_addresses")
    enabled = raw.get("enabled")
    return {
        "device_name": _name_of(raw.get("device")) or "",
        "interface": _text(raw.get("name")),
        "type": _text(raw.get("type")),
        "enabled": enabled if isinstance(enabled, bool) else None,
        "status": _name_of(raw.get("status")),
        "mac_address": _text(raw.get("mac_address")),
        "description": _text(raw.get("description")),
        "ip_addresses": _texts(addresses, "address") or None,
        "cabled": bool(cable),
        "connected_device": _name_of(peer.get("device")),
        "connected_interface": _text(peer.get("name")),
    }


def _ip_address_row(raw: dict[str, Any], _directory: Any) -> Row:
    """One IP address as a report row; its name is the address itself."""
    parent = _dict(raw.get("parent"))
    interfaces = raw.get("interfaces")
    assigned = None
    if isinstance(interfaces, list):
        parts = [
            f"{_name_of(i.get('device')) or '?'}:{i['name']}"
            for i in interfaces
            if isinstance(i, dict) and isinstance(i.get("name"), str)
        ]
        assigned = ", ".join(parts) or None
    address = _text(raw.get("address"))
    return {
        "device_name": address or "",
        "address": address,
        "prefix": _text(parent.get("prefix")),
        "namespace": _name_of(parent.get("namespace")),
        "status": _name_of(raw.get("status")),
        "role": _name_of(raw.get("role")),
        "type": _text(raw.get("type")),
        "dns_name": _text(raw.get("dns_name")),
        "description": _text(raw.get("description")),
        "tenant": _name_of(raw.get("tenant")),
        "tags": _texts(raw.get("tags"), "name") or None,
        "assigned_to": assigned,
    }


def _usable_hosts(prefix: str | None) -> tuple[int | None, int | None]:
    """``(addresses, usable host addresses)`` of a prefix; ``None`` when it cannot be read."""
    try:
        network = ipaddress.ip_network(prefix or "", strict=False)
    except ValueError:
        return None, None
    size = network.num_addresses
    if network.version == 4 and network.prefixlen < 31:
        return size, size - 2  # network and broadcast address are not for hosts
    return size, size


def _prefix_row(raw: dict[str, Any], _directory: Any) -> Row:
    """One prefix as a report row; its name is the prefix itself."""
    vlan = _dict(raw.get("vlan"))
    vid, vlan_name = vlan.get("vid"), _text(vlan.get("name"))
    vlan_text = " ".join(p for p in (str(vid) if isinstance(vid, int) else "", vlan_name) if p)
    prefix = _text(raw.get("prefix"))
    size, usable = _usable_hosts(prefix)
    addresses = raw.get("ip_addresses")
    # Only addresses whose own prefix is this one are counted: those inside a child prefix belong
    # to the child, so for a prefix with children the free number is an upper bound.
    used = len(addresses) if isinstance(addresses, list) else None
    free = max(usable - used, 0) if usable is not None and used is not None else None
    return {
        "device_name": prefix or "",
        "prefix": prefix,
        "type": _text(raw.get("type")),
        "namespace": _name_of(raw.get("namespace")),
        "status": _name_of(raw.get("status")),
        "role": _name_of(raw.get("role")),
        "description": _text(raw.get("description")),
        "tenant": _name_of(raw.get("tenant")),
        "vlan": vlan_text or None,
        "locations": _texts(raw.get("locations"), "name") or None,
        "parent": _text(_dict(raw.get("parent")).get("prefix")),
        "tags": _texts(raw.get("tags"), "name") or None,
        "size": size,
        "used_ip_count": used,
        "free_ip_count": free,
    }


def _location_row(raw: dict[str, Any], _directory: Any) -> Row:
    return {
        "device_name": _text(raw.get("name")) or "",
        "location_type": _name_of(raw.get("location_type")),
        "parent": _name_of(raw.get("parent")),
    }


@dataclass(frozen=True)
class _Table:
    """A report dataset and how its rows are read from Nautobot (GraphQL root, selection)."""

    dataset: DatasetInfo
    root: str
    selection: str
    to_row: Callable[[dict[str, Any], Any], Row]
    needs_locations: bool = False
    # Report field -> Nautobot filter name, for a field Nautobot can filter on exactly as the
    # report does (see ``_server_filters``).
    pushdown: Mapping[str, str] = field(default_factory=dict)


_TABLES = {
    table.dataset.name: table
    for table in (
        _Table(
            _dataset("devices", "device", _DEVICE_FIELDS),
            "devices",
            REPORT_DEVICE_SELECTION,
            _device_row,
            needs_locations=True,
            pushdown={"device_name": "name"},
        ),
        _Table(
            _dataset("software_versions", "items", _SOFTWARE_VERSION_FIELDS),
            "software_versions",
            SOFTWARE_VERSION_SELECTION,
            _software_version_row,
            pushdown={"version": "version"},
        ),
        _Table(
            _dataset("interfaces", "items", _INTERFACE_FIELDS),
            "interfaces",
            REPORT_INTERFACE_SELECTION,
            _interface_row,
        ),
        _Table(
            _dataset("ip_addresses", "items", _IP_ADDRESS_FIELDS),
            "ip_addresses",
            IP_ADDRESS_SELECTION,
            _ip_address_row,
        ),
        _Table(
            _dataset("prefixes", "items", _PREFIX_FIELDS),
            "prefixes",
            PREFIX_REPORT_SELECTION,
            _prefix_row,
        ),
        _Table(
            _dataset("locations", "items", _LOCATION_FIELDS),
            "locations",
            LOCATION_SELECTION,
            _location_row,
        ),
    )
}


def _server_filters(table: _Table, query: ReportQuery) -> dict[str, list[str]]:
    """The part of the query's filters Nautobot can apply, so a question about one device does not
    read the whole table.

    Only ``eq`` / ``in`` on a text field that has a Nautobot filter of the same meaning. This is
    an optimisation only: every filter is applied again in memory (``evaluate``), so a Nautobot
    filter that is looser than the report's can never add a row, and an unmapped filter is simply
    not sent. Two filters on one field both narrow (the report ANDs them), so the intersection is
    sent. An empty intersection can match nothing: it is returned as an empty list, and ``run``
    answers without a request (the Nautobot client drops an empty filter, which would read all).
    """
    wanted: dict[str, set[str]] = {}
    for flt in query.filters:
        name = table.pushdown.get(flt.field)
        if name is None or flt.op not in ("eq", "in"):
            continue
        values = flt.value if flt.op == "in" else [flt.value]
        if not all(isinstance(v, str) and v for v in values):
            continue
        current = wanted.get(name)
        wanted[name] = set(values) if current is None else current & set(values)
    return {name: sorted(values) for name, values in wanted.items()}


class NautobotReportSource:
    id = SOURCE_ID
    label = "Nautobot"

    def __init__(
        self,
        db: Session,
        *,
        actor_user_id: int | None = None,
        context_factory: ContextFactory | None = None,
    ) -> None:
        self.db = db
        self._user_id = actor_user_id
        self._context_factory = context_factory or _default_context

    def describe(self) -> list[DatasetInfo]:
        return [table.dataset for table in _TABLES.values()]

    def validate(self, query: ReportQuery) -> None:
        validate(query, self._dataset(query))

    def run(self, query: ReportQuery) -> QueryResult:
        table = self._table(query)
        validate(query, table.dataset)  # before any request to Nautobot
        filters = _server_filters(table, query)
        if any(not values for values in filters.values()):
            rows: list[Row] = []  # contradicting filters: nothing can match, nothing to read
        else:
            rows = asyncio.run(self._fetch(table, filters))
        return evaluate(query, table.dataset, rows)

    def _table(self, query: ReportQuery) -> _Table:
        table = _TABLES.get(query.dataset)
        if table is None:
            raise ReportQueryError(f"unknown dataset {query.dataset!r}")
        return table

    def _dataset(self, query: ReportQuery) -> DatasetInfo:
        return self._table(query).dataset

    async def _fetch(self, table: _Table, filters: Mapping[str, list[str]]) -> list[Row]:
        if self._user_id is None:
            raise ReportQueryError("Nautobot reports need a signed-in user")
        # Late import: ``NautobotAccessError`` lives with the reader that raises it.
        from services.ai_assistant.nautobot_query_reader import NautobotAccessError

        try:
            ctx = await self._context_factory(self._user_id)
            directory = await directory_or_none(ctx) if table.needs_locations else None
            raw = await ctx.client.list_all(
                table.root, table.selection, filters, max_items=MAX_DEVICES
            )
        except NautobotAccessError as exc:
            raise ReportQueryError(
                "Nautobot is not available: you need the permission to read Nautobot "
                "(sources.nautobot:read) and a configured Nautobot source"
            ) from exc
        except TooManyRowsError as exc:
            raise ReportQueryError(
                f"Nautobot has more than {MAX_DEVICES} {table.root.replace('_', ' ')}; "
                "a report cannot read them all"
            ) from exc
        except NautobotError as exc:
            # The library writes these messages to be shown (no URL, token or upstream text).
            logger.warning("Nautobot report source: %s", type(exc).__name__)
            raise ReportQueryError(f"Nautobot could not be read: {exc}") from exc
        return [table.to_row(row, directory) for row in raw]
