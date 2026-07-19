"use client";

import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";
import { GitSourceConfigPanel } from "@/components/features/workflow-steps/shared/git-source-config-panel";
import { GitPullHelpPanel } from "./help-panel";

export const GitPullPlugin: PluginUIComponent = {
  ConfigPanel: (props) => (
    <GitSourceConfigPanel
      {...props}
      description="Pull the latest remote changes once for the selected Settings git source."
    />
  ),
  HelpPanel: GitPullHelpPanel,
};
