import type { BatfishEditorQuestion } from "../types";
import type { ParamFieldSpec } from "./batfish-param-fields";

export const PREFIX_MATCH_TYPES = [
  "EXACT",
  "LONGEST_PREFIX_MATCH",
  "LONGER_PREFIXES",
  "SHORTER_PREFIXES",
] as const;

export const RIBS = ["main", "bgp", "evpn"] as const;

const NODES_FIELD: ParamFieldSpec = {
  kind: "text",
  key: "nodes",
  id: "batfish-nodes",
  label: "Nodes (Optional)",
  placeholder: "e.g. R1",
};

const PROPERTIES_FIELD: ParamFieldSpec = {
  kind: "text",
  key: "properties",
  id: "batfish-properties",
  label: "Properties (Optional)",
  placeholder: "e.g. NTP_Servers, TACACS_Servers",
};

/**
 * Spec-driven fields per question. The output-key field and the OSPF/BGP include
 * toggles (facts questions) are rendered by the tab after these, inside the same grid.
 * Questions with no spec entry ("generic") have their own component.
 */
export const QUESTION_FIELDS: Partial<Record<BatfishEditorQuestion, readonly ParamFieldSpec[]>> = {
  routes: [
    NODES_FIELD,
    {
      kind: "text",
      key: "network_prefix",
      id: "batfish-network-prefix",
      label: "Network Prefix (Optional)",
      placeholder: "e.g. 192.168.1.0/24",
    },
    {
      kind: "select",
      key: "prefix_match_type",
      label: "Prefix Match Type",
      options: PREFIX_MATCH_TYPES,
      fallback: "EXACT",
    },
    {
      kind: "text",
      key: "protocols",
      id: "batfish-protocols",
      label: "Protocols (Optional)",
      placeholder: "e.g. static, bgp",
    },
    {
      kind: "text",
      key: "vrfs",
      id: "batfish-vrfs",
      label: "VRFs (Optional)",
      placeholder: "e.g. default",
    },
    { kind: "select", key: "rib", label: "RIB", options: RIBS, fallback: "main" },
  ],
  reachability: [
    {
      kind: "text",
      key: "start_node",
      id: "batfish-start-node",
      label: "Start Node",
      placeholder: "e.g. R1",
      required: true,
    },
    {
      kind: "text",
      key: "end_node",
      id: "batfish-end-node",
      label: "End Node (Optional)",
      placeholder: "e.g. R2 (any destination if blank)",
    },
    {
      kind: "text",
      key: "dst_ips",
      id: "batfish-dst-ips",
      label: "Destination IPs (Optional)",
      placeholder: "e.g. 192.168.1.1",
    },
    {
      kind: "text",
      key: "src_ips",
      id: "batfish-src-ips",
      label: "Source IPs (Optional)",
      placeholder: "e.g. 10.0.0.1",
    },
    {
      kind: "list",
      key: "applications",
      id: "batfish-applications",
      label: "Applications (Optional)",
      placeholder: "e.g. SSH, HTTPS",
    },
    {
      kind: "text",
      key: "ip_protocols",
      id: "batfish-ip-protocols",
      label: "IP Protocols (Optional)",
      placeholder: "e.g. tcp",
    },
    {
      kind: "integer",
      key: "max_traces",
      id: "batfish-max-traces",
      label: "Max Traces (Optional)",
      min: 1,
    },
    { kind: "switch", key: "invert_search", id: "batfish-invert-search", label: "Invert Search" },
    { kind: "switch", key: "ignore_filters", id: "batfish-ignore-filters", label: "Ignore Filters" },
  ],
  testFilters: [
    {
      kind: "text",
      key: "node",
      id: "batfish-node",
      label: "Node",
      placeholder: "e.g. R1",
      required: true,
    },
    {
      kind: "text",
      key: "filter_name",
      id: "batfish-filter-name",
      label: "Filter Name",
      placeholder: "e.g. TEST-ACL",
      required: true,
    },
    {
      kind: "text",
      key: "dst_ips",
      id: "batfish-tf-dst-ips",
      label: "Destination IPs",
      placeholder: "e.g. 192.168.1.1",
      required: true,
    },
    {
      kind: "text",
      key: "src_ips",
      id: "batfish-tf-src-ips",
      label: "Source IPs (Optional)",
      placeholder: "e.g. 8.8.8.8",
    },
    {
      kind: "list",
      key: "applications",
      id: "batfish-tf-applications",
      label: "Applications (Optional)",
      placeholder: "e.g. SSH, TELNET",
    },
    {
      kind: "text",
      key: "ip_protocols",
      id: "batfish-tf-ip-protocols",
      label: "IP Protocols (Optional)",
      placeholder: "e.g. tcp",
    },
    {
      kind: "text",
      key: "start_location",
      id: "batfish-start-location",
      label: "Start Location (Optional)",
      placeholder: "optional",
    },
  ],
  extractFacts: [
    {
      kind: "text",
      key: "nodes_filter",
      id: "batfish-nodes-filter",
      label: "Nodes Filter (Optional)",
      placeholder: "e.g. lab (blank = every node)",
    },
  ],
  ospfFacts: [{ ...NODES_FIELD, id: "batfish-ospf-bgp-nodes" }],
  bgpFacts: [{ ...NODES_FIELD, id: "batfish-ospf-bgp-nodes" }],
  nodeProperties: [{ ...NODES_FIELD, id: "batfish-props-nodes" }, PROPERTIES_FIELD],
  interfaceProperties: [
    { ...NODES_FIELD, id: "batfish-props-nodes" },
    {
      kind: "text",
      key: "interfaces",
      id: "batfish-interfaces",
      label: "Interfaces (Optional)",
      placeholder: "e.g. GigabitEthernet0/1",
    },
    PROPERTIES_FIELD,
  ],
};
