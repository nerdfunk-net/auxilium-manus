"use client";

import { useCallback } from "react";

import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import type { PluginConfigPanelProps } from "@/components/features/workflows/types/plugin-ui";
import { CollectStatisticsHelpPanel } from "./help-panel";

const DEFAULT_RESULT = "success";

const RESULT_OPTIONS = [
  { value: "success", label: "Success" },
  { value: "failed", label: "Failed" },
] as const;

function buildCollectStatisticsConfig(
  config: Record<string, unknown>,
  patch: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    result: config.result === "failed" ? "failed" : DEFAULT_RESULT,
    ...patch,
  };
}

function CollectStatisticsConfigPanel({ config, onChange }: PluginConfigPanelProps) {
  const result = config.result === "failed" ? "failed" : DEFAULT_RESULT;

  const handleResultChange = useCallback(
    (value: string) => onChange(buildCollectStatisticsConfig(config, { result: value })),
    [config, onChange],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="space-y-1.5">
        <div className="flex items-center gap-1.5">
          <span className="font-mono text-xs font-medium">result</span>
          <Badge className="h-4 rounded px-1 text-[10px]" variant="secondary">
            string
          </Badge>
        </div>
        <Select value={result} onValueChange={handleResultChange}>
          <SelectTrigger className="h-8 text-xs focus:ring-step/40">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {RESULT_OPTIONS.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-[11px] leading-4 text-muted-foreground">
          Every device reaching this node is recorded with this result — job name/id
          and run id are resolved automatically. Wire a second Collect Statistics node
          to the other outcome handle with the opposite result to capture both.
        </p>
      </div>
    </div>
  );
}

export const CollectStatisticsPlugin = {
  ConfigPanel: CollectStatisticsConfigPanel,
  HelpPanel: CollectStatisticsHelpPanel,
};
