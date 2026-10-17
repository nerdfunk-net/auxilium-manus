"use client";

import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";
import { ShowSummaryHelpPanel } from "./help-panel";

function ShowSummaryConfigPanel() {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[11px] leading-4 text-muted-foreground">
        No configuration required. Click a failed cell in the table to see
        the detailed error for that device and step.
      </p>
    </div>
  );
}

export const ShowSummaryPlugin: PluginUIComponent = {
  ConfigPanel: ShowSummaryConfigPanel,
  HelpPanel: ShowSummaryHelpPanel,
};
