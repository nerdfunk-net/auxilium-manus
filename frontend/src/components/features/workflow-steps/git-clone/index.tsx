"use client";

import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";
import { GitSourceConfigPanel } from "@/components/features/workflow-steps/shared/git-source-config-panel";
import { GitCloneHelpPanel } from "./help-panel";

export const GitClonePlugin: PluginUIComponent = {
  ConfigPanel: (props) => (
    <GitSourceConfigPanel
      {...props}
      description="Clone or re-clone the selected Git repository before other steps run."
    />
  ),
  HelpPanel: GitCloneHelpPanel,
};
