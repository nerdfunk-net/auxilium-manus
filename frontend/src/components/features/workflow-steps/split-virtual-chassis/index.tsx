"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { SplitVirtualChassisHelpPanel } from "./help-panel";

const DEFAULT_ATTRIBUTE_BAG = "virtual_chassis";

function attributeBagFromConfig(config: Record<string, unknown>): string {
  const raw = config.attribute_bag;
  return typeof raw === "string" ? raw : DEFAULT_ATTRIBUTE_BAG;
}

function SplitVirtualChassisConfigPanel({
  config,
  onChange,
}: PluginConfigPanelProps) {
  const attributeBag = attributeBagFromConfig(config);

  const handleBagChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>) =>
      onChange({ ...config, attribute_bag: event.target.value }),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">attribute_bag</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="outline">
            optional
          </Badge>
        </div>
        <Input
          aria-label="Attribute bag name"
          className="h-7 font-mono text-xs"
          value={attributeBag}
          onChange={handleBagChange}
        />
        <p className="text-[11px] text-muted-foreground">
          Must match attribute_bag on the upstream Get Virtual Chassis step.
          Member numbering (index_regex, index_offset, index_default, index_key)
          comes from that step.
        </p>
      </div>
    </div>
  );
}

export const SplitVirtualChassisPlugin: PluginUIComponent = {
  ConfigPanel: SplitVirtualChassisConfigPanel,
  HelpPanel: SplitVirtualChassisHelpPanel,
};
