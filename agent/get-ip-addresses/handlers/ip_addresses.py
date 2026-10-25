"""The ``get_ip_addresses`` handler: the cached IP data of one device.

Step setup (Route to Agent): handler ``get_ip_addresses``, input path ``name`` (or the path in
``params.name_attribute``), output keys ``found``, ``interfaces``, ``primary_ip4``, ``problems``
with "allow missing outputs" on (``primary_ip4`` is left out when the device has none).
A device that is not in the files is an ordinary answer (``found: false``), not an error.
"""

from __future__ import annotations

from typing import Any

from manus_agent.ip_index import entry_to_answer, get_index
from manus_agent.registry import handler

DEFAULT_NAME_ATTRIBUTE = "name"


@handler("get_ip_addresses")
def get_ip_addresses(params: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    attribute = params.get("name_attribute", DEFAULT_NAME_ATTRIBUTE)
    if not isinstance(attribute, str) or not attribute:
        raise ValueError("params.name_attribute must be a non-empty text")
    name = inputs.get("attributes", {}).get(attribute)
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"the device name is missing (input path {attribute!r})")
    entry = get_index().lookup(name)
    if entry is None:
        return {"found": False, "device": name.strip(), "interfaces": [], "problems": []}
    return entry_to_answer(entry)
