"use client";

import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";
import { ShowSummaryHelpPanel } from "./help-panel";

function ShowSummaryConfigPanel() {
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg bg-teal-50 px-3 py-2 text-xs text-teal-900">
        Renders a device × step status table for this run wherever this
        step&apos;s result row is expanded in the run detail view.
      </div>
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
