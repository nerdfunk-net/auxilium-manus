import type { FilterTree } from "../condition-builder/types";

export interface SavedInventory {
  id: number;
  name: string;
  description: string | null;
  conditions: SavedConditionPayload[];
  template_category: string | null;
  template_name: string | null;
  scope: string;
  group_path: string | null;
  created_by: string;
  is_active: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface SavedConditionPayload {
  version?: number;
  tree?: FilterTree;
  field?: string;
  operator?: string;
  value?: string;
}

export interface InventoryGroupNode {
  id: string;
  name: string;
  path: string | null;
  children: InventoryGroupNode[];
}

export const ROOT_GROUP_ID = "__root__";
