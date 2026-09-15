/**
 * Commonly-used property names for Batfish's `interfaceProperties` question,
 * offered as click-to-add suggestions in the Batfish Interface Properties
 * config panel.
 *
 * Unlike BATFISH_FACT_KEYS (node-level facts, confirmed against pybatfish's
 * own NODE_PROPERTIES_REORG map), this is NOT a confirmed-exhaustive list --
 * Batfish's real interfaceProperties column set is fetched dynamically from
 * the coordinator at runtime, not embedded in the pybatfish client package,
 * so it can't be enumerated from this codebase alone. This is a curated
 * starting point per Batfish's own public question documentation; the
 * `properties` field always accepts free text, so any real property name
 * works whether or not it's listed here.
 */
export const BATFISH_INTERFACE_PROPERTY_KEYS = [
  "Access_VLAN",
  "Active",
  "All_Prefixes",
  "Allowed_VLANs",
  "Bandwidth",
  "Blacklisted",
  "Channel_Group",
  "Description",
  "Encapsulation_VLAN",
  "HSRP_Groups",
  "Incoming_Filter_Name",
  "MTU",
  "Native_VLAN",
  "Outgoing_Filter_Name",
  "Primary_Address",
  "Proxy_ARP",
  "Speed",
  "Switchport",
  "Switchport_Mode",
  "VRF",
  "Zone_Name",
] as const;
