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
