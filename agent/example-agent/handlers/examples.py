"""Example handlers. Copy this file, rename it and replace the logic with your own.

Each handler is ``handle(params, inputs) -> dict``:

* ``params``  - the static JSON object configured on the step.
* ``inputs``  - ``{"attributes": {"<path>": value, ...}, "content": {"running_config": "..."}}``;
                a path or content the device does not have is simply missing.

Return a JSON object. The step only accepts the keys its ``output_keys`` list declares.
"""

from __future__ import annotations

from typing import Any

from manus_agent.registry import handler


@handler("resolve_location")
def resolve_location(params: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Derive a short location name from a Nautobot location, e.g. "Berlin-DC1" -> "Berlin".

    Step setup: input_paths ``nautobot.location.name``, output_keys ``location``.
    With ``{"strict": true}`` as params a device without a location is an error instead of
    "unknown".
    """
    name = inputs.get("attributes", {}).get("nautobot.location.name")
    if not isinstance(name, str) or not name.strip():
        if params.get("strict"):
            raise ValueError("nautobot.location.name is missing")
        return {"location": "unknown"}
    return {"location": name.replace("_", "-").split("-")[0].strip() or "unknown"}


_DEVICES = (
    {
        "name": "ber-sw01",
        "ip_address": "10.1.0.11",
        "network_driver": "cisco_ios",
        "site": "berlin",
    },
    {
        "name": "ber-sw02",
        "ip_address": "10.1.0.12",
        "network_driver": "cisco_nxos",
        "site": "berlin",
    },
    {
        "name": "par-sw01",
        "ip_address": "10.2.0.11",
        "network_driver": "cisco_ios",
        "site": "paris",
    },
)


@handler("list_devices")
def list_devices(params: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    """Return the devices of one site, for the *Get from Agent* inventory step.

    Step setup: handler ``list_devices``, one attribute ``site`` (for example ``berlin``).
    The answer is ``{"devices": [{"name", "ip_address", "network_driver"}, ...]}``, the same rows
    as *Get from List*. Replace ``_DEVICES`` with a lookup in your own inventory.
    """
    attributes = inputs.get("attributes")
    site = attributes.get("site") if isinstance(attributes, dict) else None
    if not isinstance(site, str) or not site.strip():
        raise ValueError("attribute 'site' is required")
    wanted = site.strip().lower()
    return {
        "devices": [
            {key: device[key] for key in ("name", "ip_address", "network_driver")}
            for device in _DEVICES
            if device["site"] == wanted
        ]
    }
