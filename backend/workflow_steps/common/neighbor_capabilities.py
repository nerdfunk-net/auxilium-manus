"""LLDP / CDP capability vocabulary shared by the steps that read neighbours.

Used by ``collect-client-data`` and ``discover-network``. Pure functions, no I/O.
"""

from __future__ import annotations

import re

# Capabilities a neighbour can advertise, as a closed vocabulary. A port with a neighbour that
# bridges, routes or is a wireless access point has other devices behind it: it is an uplink.
INFRASTRUCTURE_CAPABILITIES = frozenset({"bridge", "router", "wlan_ap"})

_LLDP_CODES = {
    "b": "bridge",
    "r": "router",
    "w": "wlan_ap",
    "t": "telephone",
    "c": "docsis",
    "s": "station",
    "p": "repeater",
    "o": "other",
}
# CDP's legacy letter codes differ from LLDP's (S is Switch there, H is Host).
_CDP_CODES = {
    "r": "router",
    "t": "bridge",
    "b": "bridge",
    "s": "bridge",
    "h": "station",
    "p": "telephone",
}
_CDP_WORDS = {
    "router": "router",
    "switch": "bridge",
    "trans-bridge": "bridge",
    "source-route-bridge": "bridge",
    "host": "station",
    "phone": "telephone",
    "repeater": "repeater",
}


def parse_capabilities(raw: str | None, protocol: str) -> tuple[str, ...]:
    """Advertised capabilities as sorted names of a closed vocabulary; unknown words are dropped."""
    found: set[str] = set()
    text = raw.strip() if isinstance(raw, str) else ""
    for token in re.split(r"[,\s]+", text):
        if not token:
            continue
        if len(token) == 1:
            # CDP's capital letters are codes too ("R S I"); lower-case "r" there is Repeater.
            table = _CDP_CODES if protocol == "cdp" else _LLDP_CODES
            name = table.get(token.lower())
            if protocol == "cdp" and token == "r":
                name = "repeater"
        else:
            name = _CDP_WORDS.get(token.lower()) if protocol == "cdp" else None
        if name:
            found.add(name)
    return tuple(sorted(found))
