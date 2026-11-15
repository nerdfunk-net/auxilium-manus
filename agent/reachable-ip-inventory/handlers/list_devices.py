"""The ``list_devices`` handler: the reachable hosts of the Nautobot prefixes with a tag.

Get from Agent step setup
-------------------------
* ``handler``: ``list_devices``
* ``attributes``: ``tag`` = the name of a Nautobot tag (fixed text or ``{run_input.tag}``)
* ``timeout_seconds``: fping needs about ``count x max(addresses x 10 ms, timeout_ms)`` per prefix
  plus the DNS lookups (README.md "How long does it take"); raise it and the agent source's maximum.

Answer: ``{"devices": [{"name", "ip_address", "network_driver": ""}]}``. An empty driver becomes
the step's default.
"""

from __future__ import annotations

import sys
from typing import Any

from manus_agent.inventory import list_devices as _list_devices
from manus_agent.inventory_config import ConfigFileError, load_inventory_config
from manus_agent.registry import handler

# Read when the handlers are loaded, so a bad config.yaml stops the agent at start (exit code 3)
# instead of failing every request while /healthz stays green.
try:
    _CONFIG = load_inventory_config()
except ConfigFileError as exc:
    print(f"manus-agent: {exc}", file=sys.stderr)
    raise


@handler("list_devices")
async def list_devices(params: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    return await _list_devices(params, inputs, _CONFIG)
