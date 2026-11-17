"""Interface name shortening shared by the steps that fill the client data tables."""

from __future__ import annotations

import re

# Long interface names -> the short form the MAC address table prints. "Ethernet" is "Eth" on
# NX-OS and "Et" on IOS; names that are already short are left as they are.
_PORT_PREFIXES = {
    "gigabitethernet": "Gi",
    "tengigabitethernet": "Te",
    "twentyfivegige": "Twe",
    "fortygigabitethernet": "Fo",
    "hundredgige": "Hu",
    "fastethernet": "Fa",
    "port-channel": "Po",
    "gi": "Gi",
    "te": "Te",
    "twe": "Twe",
    "fo": "Fo",
    "hu": "Hu",
    "fa": "Fa",
    "po": "Po",
}
_PORT_NAME = re.compile(r"^([A-Za-z][A-Za-z\-]*?)\s*(\d.*)$")


def normalise_port(raw: str | None, platform: str) -> str:
    """The short form of an interface name (``GigabitEthernet1/0/5`` -> ``Gi1/0/5``).

    LLDP and CDP print long names, the MAC address table short ones; the neighbours are matched to
    MAC-table ports by this form. Unknown names (``mgmt0``, ``Vlan10``) are returned stripped.
    """
    text = raw.strip() if isinstance(raw, str) else ""
    match = _PORT_NAME.match(text)
    if match is None:
        return text
    prefix, rest = match.group(1), match.group(2)
    key = prefix.lower()
    if key == "ethernet":
        return f"{'Eth' if 'nxos' in platform else 'Et'}{rest}"
    short = _PORT_PREFIXES.get(key)
    return f"{short}{rest}" if short else text
