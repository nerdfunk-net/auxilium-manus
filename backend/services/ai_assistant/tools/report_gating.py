"""What the user's data switches allow the model to read from a report query or a stored report.

One rule for every report tool, whatever surface it sits on (the Reports page assistant, Ask the
Net): rows of the ``nautobot`` source need the inventory switch, and the addresses switch as soon
as ``serial`` or ``primary_ip4`` is selected, grouped, filtered or counted, or a list has no
``select`` (it returns every field). Rows of the report database, and of any source that is not
classified yet (fail closed), need the report-data switch. A stored snapshot is judged by the
queries of its sections, because its rows are the answer to those queries.
"""

from __future__ import annotations

from typing import Any

from models.reports import ReportQuery
from services.ai_assistant.data_sharing import DataClass, SharingPolicy, gated

# Fields of the Nautobot datasets that need the addresses switch on top of the inventory switch.
NAUTOBOT_ADDRESS_FIELDS = frozenset({"primary_ip4", "serial"})
# Datasets whose rows are addresses or interfaces as a whole: the addresses switch always applies.
NAUTOBOT_ADDRESS_DATASETS = frozenset({"interfaces", "ip_addresses", "prefixes"})
# Datasets that are only inventory names (no address, no free text).
NAUTOBOT_INVENTORY_ONLY_DATASETS = frozenset({"locations"})
# Free-text fields (descriptions): the content switch applies, as for the Ask the Net tools.
NAUTOBOT_CONTENT_FIELDS = frozenset({"description"})


_DEVICE_DATASETS = frozenset({"devices", "software_versions"})


def _fields_used(query: ReportQuery) -> set[str]:
    used = {*query.select, *query.group_by}
    used.update(f.field for f in query.filters)
    used.update(m.field for m in query.metrics if m.field)
    return used


def blocked_by_sharing(sharing: SharingPolicy, query: ReportQuery | None) -> dict[str, Any] | None:
    """The not-shared marker when the switches do not allow reading the rows of *query*, else None.

    ``query`` None (a stored section whose query cannot be read) is judged as report data.
    """
    if query is not None and query.source == "nautobot":
        marker = gated(sharing, DataClass.INVENTORY, True)
        if marker is not True:
            return marker
        if query.dataset in NAUTOBOT_INVENTORY_ONLY_DATASETS:
            return None
        everything = not query.metrics and not query.select
        used = _fields_used(query)
        # A dataset that is not classified is treated like the strictest one (fail closed).
        known = query.dataset in NAUTOBOT_ADDRESS_DATASETS or query.dataset in _DEVICE_DATASETS
        if (
            everything
            or not known
            or query.dataset in NAUTOBOT_ADDRESS_DATASETS
            or used & NAUTOBOT_ADDRESS_FIELDS
        ):
            marker = gated(sharing, DataClass.ADDRESSES, True)
            if marker is not True:
                return marker
        wants_text = everything or used & NAUTOBOT_CONTENT_FIELDS
        if query.dataset in NAUTOBOT_ADDRESS_DATASETS and wants_text:
            marker = gated(sharing, DataClass.CONTENT, True)
            if marker is not True:
                return marker
        return None
    marker = gated(sharing, DataClass.REPORT_DATA, True)
    return None if marker is True else marker
