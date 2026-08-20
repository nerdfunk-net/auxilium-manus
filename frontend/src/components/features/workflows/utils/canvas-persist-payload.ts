import type { StaticAttributeDef } from "../types/workflow-persistence";
import type {
  CanvasGroup,
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "../types/workflow-canvas";

export function canvasPersistPayload(
  allNodes: PersistedCanvasNode[],
  allEdges: WorkflowCanvasEdge[],
  groups: CanvasGroup[],
  staticAttributes: StaticAttributeDef[],
) {
  return {
    canvas_nodes: allNodes as unknown as Record<string, unknown>[],
    canvas_edges: allEdges as unknown as Record<string, unknown>[],
    canvas_groups: groups as unknown as Record<string, unknown>[],
    static_attributes: staticAttributes,
  };
}
