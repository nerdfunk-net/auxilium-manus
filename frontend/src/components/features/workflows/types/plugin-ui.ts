import type React from "react";

import type { WorkflowCanvasNode } from "@/components/features/workflows/types/workflow-canvas";

export interface PluginConfigPanelProps {
  nodeId: string;
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  onPreview: () => void;
  workflowNodes?: WorkflowCanvasNode[];
}

export interface PluginUIComponent {
  ConfigPanel: React.ComponentType<PluginConfigPanelProps>;
}
