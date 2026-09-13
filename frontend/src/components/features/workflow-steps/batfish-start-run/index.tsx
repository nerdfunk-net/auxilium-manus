"use client";

import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";
import { BatfishStartRunHelpPanel } from "./help-panel";

function BatfishStartRunConfigPanel() {
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
        Seeds an empty device context so a git-backed Init Batfish Snapshot
        step can be wired in without a live device-selection step upstream.
      </div>
      <p className="text-[11px] leading-4 text-muted-foreground">
        No configuration required. Only needed in git-mode Batfish
        workflows that select no real devices — live-mode Batfish workflows
        should keep using a normal device-selection step instead.
      </p>
    </div>
  );
}

export const BatfishStartRunPlugin: PluginUIComponent = {
  ConfigPanel: BatfishStartRunConfigPanel,
  HelpPanel: BatfishStartRunHelpPanel,
};
