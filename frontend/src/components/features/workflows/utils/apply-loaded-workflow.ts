import type { PluginDefinition } from "../types/plugin-registry";
import type {
  CanvasGroup,
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "../types/workflow-canvas";
import type {
  StaticAttributeDef,
  WorkflowResponse,
} from "../types/workflow-persistence";
import { repairOrphanGroups } from "./canvas-group-projection";
import { migrateCanvasState } from "./migrate-canvas";

export function canvasFromWorkflowResponse(
  full: WorkflowResponse,
  plugins: PluginDefinition[],
): {
  nodes: PersistedCanvasNode[];
  edges: WorkflowCanvasEdge[];
  groups: CanvasGroup[];
  staticAttributes: StaticAttributeDef[];
  migrated: boolean;
} {
  const loadedNodes = (full.canvas_nodes ?? []) as PersistedCanvasNode[];
  const loadedEdges = (full.canvas_edges ?? []) as WorkflowCanvasEdge[];
  const loadedGroups = (full.canvas_groups ?? []) as unknown as CanvasGroup[];
  const loadedStaticAttributes = (full.static_attributes ?? []) as StaticAttributeDef[];
  const { nodes, edges, migrated } = migrateCanvasState(
    loadedNodes,
    loadedEdges,
    plugins,
  );
  const groups = repairOrphanGroups(nodes, loadedGroups);
  return {
    nodes,
    edges,
    groups,
    staticAttributes: loadedStaticAttributes,
    migrated: migrated || groups.length !== loadedGroups.length,
  };
}
