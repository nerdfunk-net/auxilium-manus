import type React from "react";

import type { WorkflowCanvasEdge, WorkflowCanvasNode } from "@/components/features/workflows/types/workflow-canvas";
import type { PluginDefinition } from "@/components/features/workflows/types/plugin-registry";

export interface PluginConfigPanelProps {
  nodeId: string;
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  onPreview: () => void;
  workflowNodes?: WorkflowCanvasNode[];
  workflowEdges?: WorkflowCanvasEdge[];
  plugins?: PluginDefinition[];
}

export interface PluginUIComponent {
  ConfigPanel: React.ComponentType<PluginConfigPanelProps>;
}
