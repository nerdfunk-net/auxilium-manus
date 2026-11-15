"""The ``ping_range`` handler: ping an IPv4 range with fping, optionally resolve names.

Route to Agent step setup
-------------------------
* handler ``ping_range``
* ``input_paths``: the attribute that holds the range, e.g. ``custom.range``. Send just that one;
  with several, name it in ``params.range_attribute``. One device = one range = one scan.
* ``destination_path`` e.g. ``agent.ping``; ``output_keys``: ``hosts``, ``total``,
  ``reachable``, ``truncated``
* ``timeout_seconds``: see README.md "How long does it take"; raise it and the agent source's
  maximum for large ranges.

``params`` (all optional): ``resolve_dns`` (false), ``count`` (1), ``timeout_ms`` (500),
``include_unreachable`` (false), ``dns_timeout_seconds`` (2), ``range_attribute``.
See README.md for the range syntax and the answer.
"""

from __future__ import annotations

import os
import sys
from typing import Any

from manus_agent.ping import ping_range as _ping_range
from manus_agent.ping import settings_from_env
from manus_agent.registry import handler

# Read when the handlers are loaded, so a bad MANUS_AGENT_PING_* value stops the agent at start
# (exit code 3) instead of failing every request while /healthz stays green.
try:
    _SETTINGS = settings_from_env(os.environ)
except ValueError as exc:
    print(f"manus-agent: {exc}", file=sys.stderr)
    raise


@handler("ping_range")
async def ping_range(params: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    return await _ping_range(params, inputs, _SETTINGS)
