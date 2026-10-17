import type { PluginDefinition } from "../types/plugin-registry";
import type {
  PersistedCanvasNode,
  WorkflowCanvasEdge,
} from "../types/workflow-canvas";

export const EMPTY_WORKFLOW_NODES: PersistedCanvasNode[] = [];
export const EMPTY_WORKFLOW_EDGES: WorkflowCanvasEdge[] = [];
export const EMPTY_PLUGINS: PluginDefinition[] = [];
