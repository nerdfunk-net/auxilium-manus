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

/** Optional extra tab rendered in the step configuration modal. */
export interface PluginModalTab {
  id: string;
  label: string;
  Panel: React.ComponentType<PluginConfigPanelProps>;
  /** When omitted, the tab is always shown for this step. */
  isVisible?: (config: Record<string, unknown>) => boolean;
}

export interface PluginUIComponent {
  ConfigPanel: React.ComponentType<PluginConfigPanelProps>;
  modalTabs?: PluginModalTab[];
}
