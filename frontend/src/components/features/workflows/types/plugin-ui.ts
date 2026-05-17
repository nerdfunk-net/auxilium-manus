import type React from "react";

export interface PluginConfigPanelProps {
  nodeId: string;
  config: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
  onPreview: () => void;
}

export interface PluginUIComponent {
  ConfigPanel: React.ComponentType<PluginConfigPanelProps>;
}
