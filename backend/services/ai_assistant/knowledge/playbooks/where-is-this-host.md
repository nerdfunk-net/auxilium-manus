---
name: where-is-this-host
title: Where is this host (MAC, IP address or hostname) on the network
when: "where is this MAC; where is 10.1.1.5; which switch and port is host X on; where was this address last seen; which port is this device plugged into; find a host by MAC, IP or hostname; who has this IP; find the IP address 192.168.1.5; find a host; is this address in use; is this address used by a device or a client"
tools: [list_ip_addresses, list_devices, find_client, get_client_history, get_client_data_coverage, find_aci_endpoint]
scope: read-only
---
# Where is this host

## When to use
The user wants the switch, port, VLAN and VRF where a MAC address, an IP address or a hostname sits.
It only reads. Client data is a **stored observation** from the ARP and MAC address tables of the
devices the collection step has read, not the live network, so every answer needs its age.

## Nautobot first, client data as well
Look the address up in Nautobot first. When the address belongs to a network device (a router,
switch, firewall or other documented device), Nautobot usually has it: report the device, interface
and status. Batfish adds the addresses configured in its snapshot. Both describe **devices**; end
hosts (PCs, phones, servers, printers, access points) are not in the model and often not documented.
So "Find the IP address X" is not finished by "X is not configured on any device" or "Nautobot lists
X as unassigned": that only says no documented device owns it. The address can still be in use by a
host, and only the ARP and MAC tables (`find_client`) show that. Always call `find_client` too, and
report both sources. If Nautobot says unassigned and `find_client` finds it, say the address is in
use but not documented. If Nautobot has it and `find_client` also saw it, say where it was seen.

## Inputs to collect
- One identifier: a MAC in any notation, an IPv4 or IPv6 address, or a hostname.
- Optional: a device or site the user already suspects.

## Steps
1. If you have the Nautobot tools, look the address or name up first (`list_ip_addresses`, and
   `list_devices` for a device name). That is what is documented, not where the host was seen. An
   unassigned or missing result does not end the search: go on to step 2.
2. Call `find_client` with the identifier. Report `likely_location` (device, port, VLAN, VRF, IP,
   hostname) and quote its age (`age_seconds`, and `ip_age_seconds` when the IP came from an ARP
   collection of a different age). The other rows are switches that saw the MAC on an uplink: the
   host is behind them, so do not name them as its location.
3. If `rows` is empty, call `get_client_data_coverage` and say which devices were collected, when,
   and which tables were not (`skipped`, `not_supported`). An empty answer means "not in the stored
   data", never "the host does not exist". If the user needs the history of an address that moved,
   call `get_client_history` (it only holds the retained collections, so it is short).
4. If an ACI source is configured and the host may sit in the fabric (no `likely_location`, or the
   likely port is a fabric-facing port), call `find_aci_endpoint`. That is the APIC's current view.
   If the tool reports no ACI source, say so and carry on without it.
5. Compare and report each fact with its source: Nautobot (documented), stored client data (seen at
   a time), APIC (learned now). Say where they agree and where they differ.

## Decision points
- No `likely_location` but rows exist: the MAC was seen only on uplinks. Say the access switch was
  not collected, name the devices that saw it, and use the coverage to say which are missing.
- `is_uplink` is a heuristic (many MACs on a port), not LLDP or CDP knowledge. A lightly used trunk
  can look like an access port and a busy access port, such as a hypervisor, can look like an uplink.
  Say so when the port is a hypervisor, access point or port channel.
- Several rows for one IP (different VRFs or devices) are all reported; never pick one silently.
- If a tool says the user's data settings withhold a field, or that the permission is missing, tell
  the user and stop that source; do not guess the values.

## Report
The identifier, then: the likely location (device, port, VLAN, VRF) with its age, the other devices
that saw it and why they are not the location, what Nautobot documents, the APIC view if it was
read, and the limits (stored data, devices not collected).
