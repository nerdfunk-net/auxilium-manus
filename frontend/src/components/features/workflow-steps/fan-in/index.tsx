"use client";

import type { PluginUIComponent } from "@/components/features/workflows/types/plugin-ui";

function FanInConfigPanel() {
  return (
    <div className="flex flex-col gap-3">
      <div className="rounded-lg bg-teal-50 px-3 py-2 text-xs text-teal-900">
        Rejoins a fanned-out workflow into a single path. Per-device steps run in
        parallel child workflows up to this node; steps placed after it run once
        over all devices.
      </div>
      <p className="text-[11px] leading-4 text-muted-foreground">
        Put git or store-artifact steps after Fan In so exports commit and push
        once instead of once per device. No configuration required.
      </p>
    </div>
  );
}

export const FanInPlugin: PluginUIComponent = {
  ConfigPanel: FanInConfigPanel,
};
