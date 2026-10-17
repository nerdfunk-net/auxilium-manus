/**
 * Shared Genie "learn" feature options for the pyATS workflow-step config panels.
 *
 * Used by both Get Snapshot (`get-pyats-snapshot`) and Compare Snapshot
 * (`compare-pyats-snapshot`) so the grouped checkbox list stays identical. Get
 * Snapshot additionally offers an "all" row (`ALL_FEATURES_VALUE`); Compare
 * Snapshot renders only the explicit grouped options.
 */

export const ALL_FEATURES_VALUE = "all";

export interface FeatureOption {
  value: string;
  label: string;
}

export interface FeatureGroup {
  label: string;
  options: FeatureOption[];
}

export const FEATURE_GROUPS: FeatureGroup[] = [
  {
    label: "Routing & Switching Protocols",
    options: [
      { value: "bgp", label: "bgp" },
      { value: "ospf", label: "ospf" },
      { value: "eigrp", label: "eigrp" },
      { value: "rip", label: "rip" },
      { value: "isis", label: "isis" },
      { value: "pim", label: "pim" },
      { value: "igmp", label: "igmp" },
    ],
  },
  {
    label: "Services & Layer 2/3 Features",
    options: [
      { value: "vlan", label: "vlan" },
      { value: "stp", label: "stp" },
      { value: "lldp", label: "lldp" },
      { value: "cdp", label: "cdp" },
      { value: "arp", label: "arp" },
      { value: "dhcp", label: "dhcp" },
      { value: "nat", label: "nat" },
      { value: "acl", label: "acl" },
      { value: "vrf", label: "vrf" },
    ],
  },
  {
    label: "System & Platform Attributes",
    options: [
      { value: "interface", label: "interface" },
      { value: "platform", label: "platform" },
      { value: "routing", label: "routing" },
      { value: "config", label: "config" },
    ],
  },
];
