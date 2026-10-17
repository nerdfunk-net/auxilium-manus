"use client";

import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";

function FunnelConfigPanel() {
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg bg-step-surface px-3 py-2 text-xs text-step-surface-foreground">
        Merges many incoming connections into one before a shared destination —
        wire several steps into this node instead of drawing a separate line
        from each one to the destination.
      </div>
      <p className="text-[11px] leading-4 text-muted-foreground">
        Accepts any number of incoming edges and requires exactly one outgoing
        edge. No configuration required.
      </p>
    </div>
  );
}

export const FunnelPlugin: PluginUIComponent = {
  ConfigPanel: FunnelConfigPanel,
};
