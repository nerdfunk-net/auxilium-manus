"""The commands the collect-client-data step runs, per supported platform.

Only platforms whose ntc-templates field names ``parsing`` knows are supported: guessing the
fields of another platform would store wrong data silently.
"""

from __future__ import annotations

SUPPORTED_DEVICE_TYPES = frozenset({"cisco_ios", "cisco_xe", "cisco_nxos"})

CMD_ARP = "show ip arp"
CMD_MAC_TABLE = "show mac address-table"
# "show ip vrf" has no TextFSM template; "show vrf" has one on IOS, IOS-XE and NX-OS.
CMD_VRF_LIST = "show vrf"


def arp_in_vrf(vrf: str) -> str:
    """ARP command for one VRF; *vrf* must come from ``parsing.parse_vrf_names``."""
    return f"{CMD_ARP} vrf {vrf}"
