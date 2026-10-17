/** Mirrors backend/models/attribute_path.py — keep in sync. */

export type AttributePathNodeKind = "scalar" | "dict" | "list";

export interface AttributePathNode {
  name: string;
  path: string;
  kind: AttributePathNodeKind;
  example_value: string | null;
  item_count: number | null;
  discriminator_warning: string | null;
  children: AttributePathNode[];
}

export interface AttributePathTreeResponse {
  run_id: number;
  ancestor_node_ids: string[];
  device_count: number;
  nodes: AttributePathNode[];
}

export type AttributeState = "absent" | "null" | "empty" | "present";

export interface AttributePathResolveResult {
  device_id: string;
  device_name: string;
  state: AttributeState;
  value: string | null;
}

export interface AttributePathResolveResponse {
  run_id: number;
  results: AttributePathResolveResult[];
}
