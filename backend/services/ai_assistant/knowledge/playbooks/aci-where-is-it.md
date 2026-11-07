---
name: aci-where-is-it
title: Where is an address in the ACI fabric (leaf, port, EPG, bridge domain, VRF)
when: "where is 10.1.1.5 in ACI; which leaf or port is host X on; which EPG, bridge domain or VRF is this IP in; is this address learned by the fabric; where does this MAC live in ACI; which ACI subnet owns this IP"
tools: [list_ip_addresses, get_device, find_aci_endpoint, list_aci_subnets, list_aci_devices, find_aci_device]
scope: read-only
---
# Where is an address in the ACI fabric

## When to use
The user asks where an IPv4 address or a MAC address sits in a Cisco ACI fabric, or which EPG,
bridge domain and VRF it belongs to. It only reads: the APIC's current view, no live command.

## Inputs to collect
- The address: an IPv4 address or a MAC in any notation. IPv6 cannot be searched for an endpoint.
- Optional: the fabric (`source`) when more than one ACI source is configured.

## Steps
1. If you have the Nautobot tools, look the address up first (`list_ip_addresses`, and `get_device`
   for the device that owns it). That is what is documented; the fabric is what is learned.
2. Call `find_aci_endpoint` with the address. It returns the learned endpoint: MAC, IPs, tenant,
   application profile, EPG (or external EPG), encap and attachments (pod, leaf node ids, port or
   vPC).
3. For an IPv4 address call `list_aci_subnets` with `contains_ip`: it names the bridge domain, VRF
   and tenant that own the gateway subnet. A host can be learned, sit in a gateway subnet, or both.
4. To name a leaf in the answer, use `find_aci_device` with the node id from the attachment.
5. Report each fact with its source: Nautobot (documented), the APIC endpoint table (learned), the
   APIC subnet (configured). Say where they agree and where they differ.

## Decision points
- Empty `endpoints` means the fabric has not learned the address (a silent or aged-out host). It does
  not prove the address does not exist. Say that, and give the subnet result if there is one.
- An endpoint behind a hypervisor (VMM) shows no attachment: say the port is not visible here.
- Several endpoints for one IP (for example in two tenants with overlapping VRFs) are all reported;
  never pick one.
- Fields in `withheld_fields` are not shared by the user's settings; the endpoint and subnet tools
  need the inventory and addresses switches and say so when they are off.
- If a tool says no ACI source is configured, tell the user an administrator must add one and stop.

## Report
Address, then: learned location (leaf and port or vPC, tenant / application profile / EPG, encap),
the owning subnet (bridge domain, VRF, tenant), what Nautobot documents, and any difference.
