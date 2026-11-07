---
name: aci-can-a-reach-b
title: Can one server connect to another on a port in ACI (contract check)
when: "can server A connect to server B on tcp 443 in ACI; is port 1433 allowed between two hosts; why can web not reach db in ACI; is there a contract for this flow; is traffic between two IPs permitted by ACI"
tools: [list_ip_addresses, get_device, check_aci_connectivity, get_aci_epg, find_aci_contracts_between, get_aci_contract, search_aci_contracts, find_aci_endpoint]
scope: read-only
---
# Can one server connect to another on a port (Cisco ACI contracts)

## When to use
The user asks whether host A may open a connection to host B on a TCP or UDP port (or ping), in a
Cisco ACI fabric. The answer is the contract policy the APIC holds, not a live test.

## Inputs to collect
- The source and destination IPv4 addresses (the source opens the connection, the destination
  listens). If the user gives names, look them up in Nautobot first (`list_ip_addresses`, `get_device`).
- The protocol (tcp, udp or icmp) and, for tcp and udp, the destination port.

## Steps
1. Call `check_aci_connectivity` with both addresses, the protocol and the port.
2. Read `verdict` and `reason` per result (one result per learned endpoint of an address):
   - `permitted` (`contract_permits`, `same_epg`, `unenforced_vrf`, `preferred_group`): say which.
   - `not_permitted` (`no_contract`, `contract_wrong_port`, `same_epg_isolated`): say why. For
     `contract_wrong_port` show what the contract does allow (`entries`).
   - `unknown` (`source_not_found`, `destination_not_found`, `different_vrf`, `esg_not_evaluated`,
     `taboo_not_evaluated`): say what is missing. Never turn unknown into yes or no.
3. When it is `not_permitted` or you need detail, call `find_aci_contracts_between` for the two EPGs
   (`epg_path` of each side) and `get_aci_contract` for the subjects. If an address is not learned,
   `find_aci_endpoint` shows whether the fabric knows it under another address or MAC.
4. A contract in the opposite direction is a finding: the consumer opens the connection to the
   provider, so a contract that goes the other way does not permit this flow.

## Decision points
- Not learned does not mean absent: a silent host is not in the endpoint table. Ask the user to
  generate traffic (a ping) and ask again, or give the host's MAC.
- Different VRFs: only route leaking connects them, which is not evaluated. Say so.
- Never say traffic "flows" or "works". Say what the contracts permit. For real reachability use a
  Batfish check or a live test from a host.

## Report
Both hosts with their EPG and VRF and how the fabric knows them (learned or external subnet), the
verdict with its reason, the contracts involved and the ports they allow, and the limits returned by
the tool (service graphs, policy-based redirect, route leaking, ESGs and taboo contracts are not
evaluated).
