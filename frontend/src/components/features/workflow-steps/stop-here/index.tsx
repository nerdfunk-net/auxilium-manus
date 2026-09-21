"use client";

import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";

function StopHereConfigPanel() {
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
        Ends the run here — nothing downstream of this node executes. Inspect
        the workflow context up to this point via this step&apos;s own result
        in the run detail view.
      </div>
      <p className="text-[11px] leading-4 text-muted-foreground">
        No configuration required. Not supported inside a fan-out branch
        (between a fan-out-enabled inventory step and its Fan In node).
      </p>
    </div>
  );
}

export const StopHerePlugin: PluginUIComponent = {
  ConfigPanel: StopHereConfigPanel,
};
