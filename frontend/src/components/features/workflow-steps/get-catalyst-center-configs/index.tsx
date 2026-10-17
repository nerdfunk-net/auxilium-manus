"use client";

import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";
import { GetCatalystCenterConfigsHelpPanel } from "./help-panel";

function GetCatalystCenterConfigsConfigPanel() {
  return (
    <div className="flex flex-col gap-3">
      <p className="text-[11px] leading-4 text-muted-foreground">
        No configuration required. Devices must come from Catalyst Center.
      </p>
    </div>
  );
}

export const GetCatalystCenterConfigsPlugin: PluginUIComponent = {
  ConfigPanel: GetCatalystCenterConfigsConfigPanel,
  HelpPanel: GetCatalystCenterConfigsHelpPanel,
};
