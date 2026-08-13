"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import type {
  PluginConfigPanelProps,
  PluginUIComponent,
} from "@/components/features/workflows/types/plugin-ui";

import { GetPyatsConfigHelpPanel } from "./help-panel";

const OUTPUT_KEY = "output_key";

function outputKeyFromConfig(config: Record<string, unknown>): string {
  return typeof config[OUTPUT_KEY] === "string" ? (config[OUTPUT_KEY] as string) : "";
}

function GetPyatsConfigConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const outputKey = outputKeyFromConfig(config);

  const handleOutputKeyChange = useCallback(
    (value: string) => {
      onChange({ ...config, [OUTPUT_KEY]: value });
    },
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">{OUTPUT_KEY}</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Input
          value={outputKey}
          onChange={(event) => handleOutputKeyChange(event.target.value)}
          placeholder="pyats_config"
          className="h-8 font-mono text-xs"
        />
        <p className="text-[11px] leading-4 text-muted-foreground">
          Downstream steps reference this key in{" "}
          <span className="font-mono">device.parsed.{outputKey || "output_key"}</span>, nested
          under &quot;running&quot;.
        </p>
      </div>
    </div>
  );
}

export const GetPyatsConfigPlugin: PluginUIComponent = {
  ConfigPanel: GetPyatsConfigConfigPanel,
  HelpPanel: GetPyatsConfigHelpPanel,
};
