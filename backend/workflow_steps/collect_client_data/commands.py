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


# Neighbours of the ports: both protocols, because a switch may run either. Each has an
# ntc-templates template on IOS, IOS-XE and NX-OS (verified in the installed index).
CMD_LLDP = "show lldp neighbors detail"
CMD_CDP = "show cdp neighbors detail"
CMD_CHANNELS_IOS = "show etherchannel summary"
CMD_CHANNELS_NXOS = "show port-channel summary"
NEIGHBOR_COMMANDS = (CMD_LLDP, CMD_CDP)


def channel_command(device_type: str) -> str:
    """The command that lists port-channels and their member ports."""
    return CMD_CHANNELS_NXOS if "nxos" in device_type else CMD_CHANNELS_IOS


def arp_in_vrf(vrf: str) -> str:
    """ARP command for one VRF; *vrf* must come from ``parsing.parse_vrf_names``."""
    return f"{CMD_ARP} vrf {vrf}"
