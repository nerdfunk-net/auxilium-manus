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
        everything = not query.metrics and not query.select
        if everything or _fields_used(query) & NAUTOBOT_ADDRESS_FIELDS:
            marker = gated(sharing, DataClass.ADDRESSES, True)
            if marker is not True:
                return marker
        return None
    marker = gated(sharing, DataClass.REPORT_DATA, True)
    return None if marker is True else marker
